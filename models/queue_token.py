# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import hashlib
from datetime import datetime, timedelta
import logging

_logger = logging.getLogger(__name__)

class QueueToken(models.Model):
    _name = 'queue.token'
    _description = 'Token Hàng Đợi Bệnh Nhân'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'priority desc, create_date asc'

    name = fields.Char(string='Mã Token', readonly=True, default=lambda self: _('New'))
    patient_id = fields.Many2one('res.partner', string='Bệnh Nhân', required=True, domain=[('is_patient', '=', True)])
    service_id = fields.Many2one('queue.service', string='Dịch Vụ', required=True)
    room_id = fields.Many2one('queue.room', string='Phòng Được Chỉ Định', tracking=True)
    position = fields.Integer(string='Vị Trí Trong Hàng', tracking=True)
    priority = fields.Integer(string='Mức Ưu Tiên', default=0, tracking=True)
    priority_id = fields.Many2one('queue.priority', string='Loại Ưu Tiên', tracking=True)
    estimated_wait_time = fields.Float(string='Thời Gian Chờ Ước Tính (phút)', compute='_compute_wait_time')
    state = fields.Selection([
        ('draft', 'Đã Lên Lịch'),  # Trạng thái mới này cho token đã tạo nhưng chưa đưa vào hàng đợi
        ('waiting', 'Đang Đợi'),
        ('in_progress', 'Đang Phục Vụ'),
        ('completed', 'Hoàn Thành'),
        ('cancelled', 'Đã Hủy')
    ], string='Trạng Thái', default='draft', tracking=True)
    start_time = fields.Datetime(string='Thời Gian Bắt Đầu')
    end_time = fields.Datetime(string='Thời Gian Kết Thúc')
    actual_duration = fields.Float(string='Thời Gian Thực Tế (phút)', compute='_compute_duration', store=True)
    notes = fields.Text(string='Ghi Chú')
    next_service_id = fields.Many2one('queue.service', string='Dịch Vụ Tiếp Theo', compute='_compute_next_service')
    package_id = fields.Many2one('queue.package', string='Gói Dịch Vụ', related='patient_id.queue_package_id')
    emergency = fields.Boolean(string='Khẩn Cấp', default=False, tracking=True)
    color = fields.Integer(string='Màu', compute='_compute_color')
    service_group_id = fields.Many2one('queue.service.group', string='Nhóm Dịch Vụ')
    is_parallel = fields.Boolean(string='Là Dịch Vụ Song Song', compute='_compute_is_parallel', store=True)
    parallel_token_ids = fields.Many2many('queue.token', 'queue_token_parallel_rel', 
                                       'token_id', 'parallel_token_id', 
                                       string='Token Song Song', 
                                       help="Các token khác cùng nhóm dịch vụ song song với token này")
    origin_token_id = fields.Many2one('queue.token', string='Token Gốc', 
                                   help="Token gốc tạo ra token này")
    
    service_type = fields.Selection([
        ('health_check', 'Khám Sức Khỏe Định Kỳ'),
        ('insurance', 'Khám Bảo Hiểm'),
        ('emergency', 'Cấp Cứu'),
        ('regular', 'Khám Thường'),
    ], string='Loại Dịch Vụ', default='regular', tracking=True)
    
    health_check_batch_id = fields.Many2one('health.check.batch', string='Đợt Khám Sức Khỏe')
    next_recommended_service_id = fields.Many2one(
        'queue.service', 
        string='Dịch Vụ Đề Xuất Tiếp Theo', 
        compute='_compute_next_recommended_service'
    )

    @api.depends('service_group_id')
    def _compute_is_parallel(self):
        for token in self:
            if token.service_group_id and len(token.service_group_id.service_ids) > 1:
                token.is_parallel = True
            else:
                token.is_parallel = False

    @api.model_create_multi
    def create(self, vals_list):
        """
        Ghi đè phương thức create để tạo mã token tự động và thực hiện quy trình phân phối
        Quy trình:
        1. Tạo mã token
        2. Tính toán mức ưu tiên dựa trên thông tin bệnh nhân
        3. Chỉ định phòng bằng thuật toán hash
        4. Thêm vào hàng đợi và sắp xếp theo ưu tiên
        """
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('queue.token') or _('New')

        tokens = super(QueueToken, self).create(vals_list)

        # Xử lý từng token sau khi tạo
        for token in tokens:
            # Tính toán mức ưu tiên dựa trên thông tin bệnh nhân
            token._calculate_priority()

            # Chỉ định phòng bằng thuật toán hash
            token._assign_room_by_hash()

            # Thêm vào hàng đợi và sắp xếp
            token._add_to_queue_and_sort()

            # Gửi thông báo
            token._send_notifications('new_token')

        return tokens

    def _calculate_priority(self):
        """
        Tính toán mức ưu tiên dựa trên thuộc tính bệnh nhân

        Quy tắc ưu tiên:
        - Khẩn cấp: 10
        - Mức độ ưu tiên bác sĩ chỉ định: 5
        - VIP: 4
        - Tình trạng cấp thiết: 3
        - Mang thai/Khuyết tật: 2
        - Người cao tuổi (>65): 1
        - Thông thường: 0
        """
        for token in self:
            patient = token.patient_id
            priority = 0

            # Kiểm tra cờ khẩn cấp
            if token.emergency:
                priority = 10
                token.priority = priority
                token.priority_id = self.env.ref('hospital_queue_management.priority_emergency', False)
                return

            # Ưu tiên theo độ tuổi
            if patient.age >= 65:
                priority = max(priority, 1)

            # Kiểm tra mang thai hoặc khuyết tật
            if patient.is_pregnant or patient.is_disabled:
                priority = max(priority, 2)

            # Kiểm tra tình trạng y tế cấp thiết
            if patient.has_urgent_condition:
                priority = max(priority, 3)

            # Bệnh nhân VIP
            if patient.is_vip:
                priority = max(priority, 4)

            # Ưu tiên đặc biệt do bác sĩ chỉ định
            if patient.doctor_assigned_priority:
                priority = max(priority, 5)

            # Đặt mức ưu tiên
            token.priority = priority

            # Đặt loại ưu tiên tương ứng
            if priority == 0:
                token.priority_id = self.env.ref('hospital_queue_management.priority_normal', False)
            elif priority == 1:
                token.priority_id = self.env.ref('hospital_queue_management.priority_elderly', False)
            elif priority == 2:
                token.priority_id = self.env.ref('hospital_queue_management.priority_special_condition', False)
            elif priority == 3:
                token.priority_id = self.env.ref('hospital_queue_management.priority_urgent', False)
            elif priority == 4:
                token.priority_id = self.env.ref('hospital_queue_management.priority_vip', False)
            elif priority >= 5:
                token.priority_id = self.env.ref('hospital_queue_management.priority_doctor_assigned', False)

    def _assign_room_by_hash(self):
        """
        Chỉ định phòng cho bệnh nhân sử dụng thuật toán hash và cân bằng tải

        Thuật toán:
        1. Nếu bệnh nhân ưu tiên cao -> chỉ định vào phòng ít tải nhất
        2. Bệnh nhân thông thường -> sử dụng hàm hash để phân bổ đều
        3. Nếu phòng đã quá tải (>150% so với phòng ít nhất) -> chuyển sang phòng ít tải
        """
        for token in self:
            # Tìm các phòng có thể thực hiện dịch vụ này
            available_rooms = self.env['queue.room'].search([
                ('service_id', '=', token.service_id.id),
                ('state', '=', 'open')
            ])

            if not available_rooms:
                raise UserError(_("Không có phòng khả dụng cho dịch vụ này!"))

            # Với bệnh nhân ưu tiên cao, chỉ định phòng ít tải nhất
            if token.priority > 0:
                least_loaded_room = self._get_least_loaded_room(available_rooms)
                token.room_id = least_loaded_room.id
            else:
                # Với bệnh nhân thông thường, sử dụng hash để phân bổ đều
                hash_input = f"{token.patient_id.id}-{token.service_id.id}"
                hash_value = int(hashlib.md5(hash_input.encode()).hexdigest(), 16)
                room_index = hash_value % len(available_rooms)
                selected_room = available_rooms[room_index]

                # Kiểm tra nếu phòng được chọn đã quá tải
                least_loaded_room = self._get_least_loaded_room(available_rooms)
                if self._get_room_load(selected_room) > self._get_room_load(least_loaded_room) * 1.5:
                    # Nếu quá tải >150% so với phòng ít nhất, chuyển sang phòng ít tải
                    token.room_id = least_loaded_room.id
                else:
                    token.room_id = selected_room.id

    def _get_least_loaded_room(self, rooms):
        """
        Tìm phòng có tải thấp nhất trong danh sách phòng

        Tham số:
            rooms: Recordset các phòng cần kiểm tra

        Trả về:
            room: Phòng có tải thấp nhất
        """
        if not rooms:
            return False

        min_load = float('inf')
        least_loaded_room = rooms[0]

        for room in rooms:
            room_load = self._get_room_load(room)
            if room_load < min_load:
                min_load = room_load
                least_loaded_room = room

        return least_loaded_room

    def _get_room_load(self, room):
        """
        Tính toán tải của phòng (số người đợi / công suất)

        Tham số:
            room: Phòng cần tính tải

        Trả về:
            float: Tỷ lệ tải (số người đợi / công suất)
        """
        waiting_count = self.search_count([
            ('room_id', '=', room.id),
            ('state', '=', 'waiting')
        ])
        return waiting_count / room.capacity if room.capacity > 0 else float('inf')

    def _add_to_queue_and_sort(self):
        """
        Thêm token vào hàng đợi và sắp xếp dựa trên ưu tiên và thời gian
        Quy tắc sắp xếp:
        1. Ưu tiên cao được xếp trước
        2. Với cùng mức ưu tiên, ai đến trước được phục vụ trước (FIFO)
        """
        for token in self:
            if token.state == 'draft' and not token.is_parallel:
                # Chỉ chuyển sang waiting nếu không phải token song song
                token.state = 'waiting'

            # Lấy tất cả token đang đợi trong cùng phòng
            waiting_tokens = self.search([
                ('room_id', '=', token.room_id.id),
                ('state', '=', 'waiting')
            ])

            # Sắp xếp theo mức ưu tiên (giảm dần) và thời gian tạo (tăng dần)
            sorted_tokens = waiting_tokens.sorted(key=lambda r: (-r.priority, r.create_date))

            # Cập nhật vị trí cho mỗi token
            for index, t in enumerate(sorted_tokens):
                t.position = index + 1

            # Thông báo thay đổi hàng đợi đến màn hình hiển thị phòng
            self._notify_queue_change(token.room_id)

    def _compute_wait_time(self):
        """
        Tính toán thời gian chờ ước tính dựa trên vị trí và thời gian trung bình của dịch vụ
        """
        for token in self:
            if token.state == 'waiting':
                avg_duration = token.service_id.average_duration
                tokens_ahead = token.position - 1 if token.position > 0 else 0
                token.estimated_wait_time = tokens_ahead * avg_duration
            else:
                token.estimated_wait_time = 0

    @api.depends('start_time', 'end_time')
    def _compute_duration(self):
        """
        Tính toán thời gian phục vụ thực tế
        """
        for token in self:
            if token.start_time and token.end_time:
                duration = (token.end_time - token.start_time).total_seconds() / 60
                token.actual_duration = duration
            else:
                token.actual_duration = 0

    def _compute_next_service(self):
        """Xác định dịch vụ tiếp theo dựa trên dịch vụ hiện tại và gói dịch vụ"""
        for token in self:
            next_service = self._get_next_service(token.service_id, token.package_id)
            token.next_service_id = next_service.id if next_service else False

    def _get_next_service(self, current_service, package):
        """Lấy dịch vụ tiếp theo dựa trên dịch vụ hiện tại và gói dịch vụ"""
        if not current_service or not package:
            _logger.info("Thiếu thông tin: current_service=%s, package=%s", 
                        current_service and current_service.name, 
                        package and package.name)
            return False

        # Lấy tất cả tuyến đường có thể từ dịch vụ hiện tại
        routes = self.env['queue.service.route'].search([
            ('service_from_id', '=', current_service.id)
        ], order='sequence')
        
        _logger.info("Tìm thấy %d tuyến đường cho dịch vụ %s", len(routes), current_service.name)
        if not routes:
            _logger.info("Không tìm thấy tuyến đường nào cho dịch vụ %s", current_service.name)
            return False
        
        # Ghi log tất cả các tuyến đường tìm thấy
        for route in routes:
            _logger.info("Tuyến đường: %s -> %s, Gói: %s", 
                        route.service_from_id.name, 
                        route.service_to_id.name, 
                        route.package_id and route.package_id.name or "Không có")
        
        # Tìm tuyến đường cụ thể cho gói
        package_routes = routes.filtered(lambda r: r.package_id and r.package_id.id == package.id)
        if package_routes:
            _logger.info("Tìm thấy tuyến đường theo gói %s: %s -> %s", 
                        package.name, 
                        package_routes[0].service_from_id.name, 
                        package_routes[0].service_to_id.name)
            return package_routes[0].service_to_id
        
        # Tìm tuyến đường không có gói cụ thể (chung cho tất cả)
        general_routes = routes.filtered(lambda r: not r.package_id)
        if general_routes:
            _logger.info("Tìm thấy tuyến đường chung: %s -> %s", 
                        general_routes[0].service_from_id.name, 
                        general_routes[0].service_to_id.name)
            return general_routes[0].service_to_id
    
        # Nếu không có tuyến đường nào phù hợp, trả về tuyến đầu tiên
        _logger.info("Không tìm thấy tuyến đường phù hợp, sử dụng tuyến đầu tiên: %s -> %s", 
                    routes[0].service_from_id.name, 
                    routes[0].service_to_id.name)
        return routes[0].service_to_id

    def _compute_color(self):
        """Tính toán màu sắc cho giao diện kanban dựa trên trạng thái và mức độ ưu tiên"""
        for token in self:
            if token.emergency:
                token.color = 1  # Màu đỏ
            elif token.priority >= 5:
                token.color = 2  # Màu cam
            elif token.priority >= 3:
                token.color = 3  # Màu vàng
            elif token.state == 'waiting':
                token.color = 5  # Màu xanh dương
            elif token.state == 'in_progress':
                token.color = 6  # Màu tím
            elif token.state == 'completed':
                token.color = 10  # Màu xanh lá cây
            else:
                token.color = 0  # Màu xám cho trạng thái hủy hoặc nháp

    def _notify_queue_change(self, room):
        """Thông báo cho màn hình phòng về sự thay đổi hàng đợi"""
        self.env['bus.bus']._sendone(
            f'room_display_{room.id}',
            'queue_updated',
            {'room_id': room.id}
        )

    def action_start_service(self):
        """Bắt đầu phục vụ token này"""
        for token in self:
            if token.state != 'waiting':
                raise UserError(_("Chỉ có thể bắt đầu các token đang ở trạng thái chờ."))

            token.write({
                'state': 'in_progress',
                'start_time': fields.Datetime.now(),
                'position': 0
            })

            # Sắp xếp lại hàng đợi vì token này đang được phục vụ
            waiting_tokens = self.search([
                ('room_id', '=', token.room_id.id),
                ('state', '=', 'waiting')
            ])

            # Sắp xếp theo ưu tiên (giảm dần) và ngày tạo (tăng dần)
            sorted_tokens = waiting_tokens.sorted(key=lambda r: (-r.priority, r.create_date))

            # Cập nhật vị trí trong hàng đợi
            for index, t in enumerate(sorted_tokens):
                t.position = index + 1

            # Thông báo cho màn hình phòng về sự thay đổi hàng đợi
            self._notify_queue_change(token.room_id)
    
    def action_cancel(self):
        """Hủy token này"""
        for token in self:
            if token.state in ['completed', 'cancelled']:
                raise UserError(_("Không thể hủy một token đã hoàn thành hoặc đã bị hủy."))

            token.write({
                'state': 'cancelled'
            })

            # Sắp xếp lại hàng đợi
            self._add_to_queue_and_sort()

    def action_emergency_override(self):
        """Đánh dấu token là khẩn cấp và đưa lên đầu hàng đợi"""
        for token in self:
            # Tìm mức ưu tiên khẩn cấp dựa trên code thay vì external ID
            priority_emergency = self.env['queue.priority'].search([('code', '=', 'emergency')], limit=1)
            
            if not priority_emergency:
                # Nếu không tìm thấy, tạo mới
                priority_emergency = self.env['queue.priority'].create({
                    'name': 'Khẩn Cấp',
                    'code': 'emergency',
                    'priority_level': 10,
                    'color': 1
                })
            
            token.write({
                'emergency': True,
                'priority': 10,
                'priority_id': priority_emergency.id
            })

            # Sắp xếp lại hàng đợi
            token._add_to_queue_and_sort()

    def _predict_next_service(self, patient_id, current_service_id, package_id=False):
        """
        Phương thức nâng cao để dự đoán dịch vụ tiếp theo cho bệnh nhân
        Sử dụng kết hợp quy tắc nghiệp vụ và tuyến đường được cấu hình
        """
        # Lấy thông tin cần thiết
        patient = self.env['res.partner'].browse(patient_id)
        current_service = self.env['queue.service'].browse(current_service_id)
        package = self.env['queue.package'].browse(package_id) if package_id else patient.queue_package_id

        # Tìm tất cả các tuyến đường có thể từ dịch vụ hiện tại
        all_routes = self.env['queue.service.route'].search([
            ('service_from_id', '=', current_service.id)
        ], order='sequence')

        # Nếu không có tuyến đường, trả về False
        if not all_routes:
            return False

        # Ưu tiên tuyến đường cụ thể cho gói dịch vụ nếu có
        if package:
            package_routes = all_routes.filtered(lambda r: r.package_id.id == package.id)
            if package_routes:
                return package_routes[0].service_to_id

        # Xác định dịch vụ tiếp theo dựa trên điều kiện
        for route in all_routes:
            if not route.condition or not route.condition.strip():
                # Nếu không có điều kiện, sử dụng tuyến đường mặc định
                return route.service_to_id
            else:
                # Đánh giá điều kiện, sử dụng eval() cẩn thận
                # Chuẩn bị môi trường an toàn để đánh giá
                local_dict = {
                    'patient': patient,
                    'current_service': current_service,
                    'package': package,
                }
                try:
                    if eval(route.condition, {'__builtins__': {}}, local_dict):
                        return route.service_to_id
                except Exception as e:
                    # Ghi log lỗi nhưng không làm gián đoạn luồng
                    _logger.error(f"Lỗi khi đánh giá điều kiện tuyến: {str(e)}")

        # Mặc định, trả về tuyến đường đầu tiên
        return all_routes[0].service_to_id

    # Thêm các phương thức này vào class QueueToken
    def _send_notifications(self, notification_type):
        """
        Gửi thông báo dựa trên loại thông báo và cấu hình hệ thống

        Tham số:
            notification_type (str): Loại thông báo (new_token, token_called, room_change)
        """
        self.ensure_one()
        patient = self.patient_id

        # Kiểm tra cấu hình thông báo
        IrConfig = self.env['ir.config_parameter'].sudo()
        enable_sms = IrConfig.get_param('hospital_queue_management.enable_sms', 'False').lower() == 'true'
        enable_email = IrConfig.get_param('hospital_queue_management.enable_email', 'False').lower() == 'true'

        # Gửi thông báo SMS nếu được kích hoạt và bệnh nhân có số điện thoại
        if enable_sms and patient.mobile:
            try:
                if notification_type == 'new_token':
                    template_id = int(IrConfig.get_param('hospital_queue_management.sms_template_id')) or \
                                self.env.ref('hospital_queue_management.sms_template_new_token').id
                elif notification_type == 'token_called':
                    template_id = self.env.ref('hospital_queue_management.sms_template_token_called').id
                elif notification_type == 'room_change':
                    template_id = self.env.ref('hospital_queue_management.sms_template_room_change').id

                if template_id:
                    self.env['sms.template'].browse(template_id).send_sms(self.id)
            except Exception as e:
                _logger.error("Lỗi khi gửi SMS: %s", str(e))

        # Gửi thông báo email nếu được kích hoạt và bệnh nhân có email
        if enable_email and patient.email:
            try:
                if notification_type == 'new_token':
                    template_id = int(IrConfig.get_param('hospital_queue_management.email_template_id')) or \
                                self.env.ref('hospital_queue_management.email_template_new_token').id
                elif notification_type == 'token_called':
                    template_id = self.env.ref('hospital_queue_management.email_template_token_called').id
                elif notification_type == 'room_change':
                    template_id = self.env.ref('hospital_queue_management.email_template_room_change').id

                if template_id:
                    template = self.env['mail.template'].browse(template_id)
                    template.send_mail(self.id, force_send=True)
            except Exception as e:
                _logger.error("Lỗi khi gửi email: %s", str(e))

    @api.model
    def _run_load_balancing(self):
        """Công việc định kỳ cân bằng tải giữa các phòng"""
        # Lấy cấu hình từ tham số hệ thống
        IrConfig = self.env['ir.config_parameter'].sudo()
        overload_threshold = float(IrConfig.get_param('hospital_queue_management.overload_threshold', '150.0'))
        wait_threshold = float(IrConfig.get_param('hospital_queue_management.wait_threshold', '30.0'))
        max_patients_to_move = int(IrConfig.get_param('hospital_queue_management.max_patients_to_move', '3'))
        
        # Tìm tất cả các phòng mở để tính toán tải
        open_rooms = self.env['queue.room'].search([('state', '=', 'open')])
        
        # Nếu không có phòng mở nào, không thực hiện cân bằng tải
        if not open_rooms:
            return
        
        # Nhóm phòng theo dịch vụ
        rooms_by_service = {}
        for room in open_rooms:
            service_id = room.service_id.id
            if service_id not in rooms_by_service:
                rooms_by_service[service_id] = []
            rooms_by_service[service_id].append(room)
        
        # Phân loại phòng thành quá tải và nhàn rỗi
        overloaded_rooms = []
        underloaded_rooms = []
        
        for room in open_rooms:
            # Tính tải dựa trên thời gian chờ ước tính
            if room.estimated_wait_time > wait_threshold:
                overloaded_rooms.append(room)
            elif room.queue_length <= 2:  # Phòng có ít hơn hoặc bằng 2 token đang chờ
                underloaded_rooms.append(room)
        
        # Xử lý các phòng đã đóng - Thêm mới
        closed_rooms = self.env['queue.room'].search([('state', '!=', 'open')])
        for closed_room in closed_rooms:
            # Tìm các token đang chờ trong phòng đã đóng
            waiting_tokens = self.search([
                ('room_id', '=', closed_room.id),
                ('state', '=', 'waiting')
            ])
            
            if not waiting_tokens:
                continue
                
            # Tìm phòng mở cùng dịch vụ
            service_id = closed_room.service_id.id
            compatible_open_rooms = [r for r in open_rooms if r.service_id.id == service_id]
            
            if not compatible_open_rooms:
                continue
                
            # Tìm phòng ít tải nhất
            target_room = min(compatible_open_rooms, key=lambda r: r.estimated_wait_time)
            
            # Di chuyển tất cả các token từ phòng đóng sang phòng mở
            for token in waiting_tokens:
                old_room = token.room_id
                token.room_id = target_room.id
                token.message_post(
                    body=_(f"Token được chuyển từ phòng đã đóng {old_room.name} sang phòng đang mở {target_room.name}."),
                    subject=_("Thông báo chuyển phòng tự động")
                )
                # Gửi thông báo cho bệnh nhân nếu cần
                token._send_notifications('room_change')
                
            # Sắp xếp lại thứ tự trong phòng đích
            self._reorder_room_queue(target_room)
            
            # Thông báo cho màn hình hiển thị
            self._notify_queue_change(target_room)
        
        # Xử lý các phòng quá tải (giữ nguyên phần này từ code gốc)
        for o_room in overloaded_rooms:
            service = o_room.service_id
            
            # Tìm các phòng ít tải tương thích
            compatible_rooms = [
                r for r in underloaded_rooms
                if r.service_id.id == service.id
            ]
            
            if compatible_rooms:
                # Lấy các token để di chuyển (tối đa theo cấu hình)
                tokens_to_move = self.search([
                    ('room_id', '=', o_room.id),
                    ('state', '=', 'waiting')
                ], order='position desc', limit=max_patients_to_move)
                
                # Di chuyển các token đến phòng tương thích ít tải nhất
                target_room = min(compatible_rooms, key=lambda r: r.estimated_wait_time)
                for token in tokens_to_move:
                    old_room = token.room_id
                    token.room_id = target_room.id
                    # Gửi thông báo cho bệnh nhân
                    token.message_post(
                        body=_(f"Dịch vụ của bạn đã được chuyển từ phòng {old_room.name} sang phòng {target_room.name} để giảm thời gian chờ."),
                        subject=_("Thông báo chuyển phòng")
                    )
                    token._send_notifications('room_change')
                
                # Sắp xếp lại cả hai phòng
                self._reorder_room_queue(o_room)
                self._reorder_room_queue(target_room)
                
                # Thông báo cho màn hình các phòng
                self._notify_queue_change(o_room)
                self._notify_queue_change(target_room)

    # Thêm phương thức hỗ trợ sắp xếp lại hàng đợi trong phòng
    def _reorder_room_queue(self, room):
        """Sắp xếp lại thứ tự hàng đợi trong một phòng"""
        waiting_tokens = self.search([
            ('room_id', '=', room.id),
            ('state', '=', 'waiting')
        ])
        
        # Sắp xếp theo mức ưu tiên (giảm dần) và thời gian tạo (tăng dần)
        sorted_tokens = waiting_tokens.sorted(key=lambda r: (-r.priority, r.create_date))
        
        # Cập nhật vị trí
        for index, token in enumerate(sorted_tokens):
            token.position = index + 1
    
    # Thêm các phương thức mới vào queue_token.py để xử lý nhóm dịch vụ
    def _process_service_group_completion(self, token, service_group, patient, package):
        """Xử lý hoàn thành dịch vụ theo nhóm"""
        # Kiểm tra xem tất cả các dịch vụ trong nhóm đã hoàn thành chưa
        group_completed = self._check_service_group_completion(service_group, patient)
        
        if group_completed:
            _logger.info("Nhóm dịch vụ %s đã hoàn thành. Tìm nhóm tiếp theo", service_group.name)
            # Tìm nhóm dịch vụ tiếp theo
            next_group = self._get_next_service_group(service_group, package)
            
            if next_group:
                _logger.info("Tìm thấy nhóm dịch vụ tiếp theo: %s", next_group.name)
                # Tạo token cho tất cả dịch vụ trong nhóm tiếp theo
                self._create_tokens_for_service_group(next_group, patient, token)
            else:
                _logger.info("Không có nhóm dịch vụ tiếp theo cho bệnh nhân %s", patient.name)
                # Thông báo hoàn thành
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Hoàn thành dịch vụ'),
                        'message': _('Đã hoàn thành tất cả các dịch vụ cho bệnh nhân %s') % patient.name,
                        'sticky': False,
                        'type': 'info',
                    }
                }

    def _check_service_group_completion(self, service_group, patient):
        """Kiểm tra xem nhóm dịch vụ đã hoàn thành chưa dựa trên chính sách hoàn thành"""
        if not service_group or not patient:
            return False
        
        # Kiểm tra bảng completed_service_ids đã được tạo chưa
        if not hasattr(patient, 'completed_service_ids'):
            _logger.error("Bảng completed_service_ids không tồn tại trong model res.partner")
            return False
            
        # Lấy các dịch vụ đã hoàn thành
        completed_services = patient.completed_service_ids
        # Lấy tất cả dịch vụ trong nhóm
        group_services = service_group.service_ids
        
        _logger.info("Kiểm tra hoàn thành nhóm %s: Dịch vụ hoàn thành: %s, Dịch vụ trong nhóm: %s", 
                    service_group.name, 
                    ', '.join(completed_services.mapped('name')), 
                    ', '.join(group_services.mapped('name')))
        
        # Đếm số lượng dịch vụ đã hoàn thành trong nhóm
        completed_in_group = len(group_services & completed_services)
        total_in_group = len(group_services)
        
        _logger.info("Đã hoàn thành %d/%d dịch vụ trong nhóm %s", 
                    completed_in_group, total_in_group, service_group.name)
        
        # Nếu không có dịch vụ trong nhóm
        if total_in_group == 0:
            return True
        
        # Kiểm tra theo chính sách hoàn thành
        if service_group.completion_policy == 'all':
            # Phải hoàn thành tất cả dịch vụ
            return completed_in_group == total_in_group
        elif service_group.completion_policy == 'any':
            # Chỉ cần hoàn thành bất kỳ dịch vụ nào
            return completed_in_group > 0
        elif service_group.completion_policy == 'custom':
            # Áp dụng quy tắc tùy chỉnh
            if service_group.custom_rule:
                # Tạo môi trường an toàn để đánh giá biểu thức
                locals_dict = {
                    'completed_services': completed_in_group,
                    'total_services': total_in_group,
                    'completion_ratio': completed_in_group / total_in_group if total_in_group > 0 else 0
                }
                try:
                    return eval(service_group.custom_rule, {'__builtins__': {}}, locals_dict)
                except Exception as e:
                    _logger.error("Lỗi khi đánh giá quy tắc hoàn thành: %s", str(e))
                    return False
            return completed_in_group == total_in_group
        
        return False

    def _get_next_service_group(self, current_group, package):
        """Lấy nhóm dịch vụ tiếp theo dựa trên nhóm hiện tại và gói dịch vụ"""
        if not current_group:
            return False
        
        # Tìm tất cả tuyến đường từ nhóm hiện tại
        routes = self.env['queue.service.group.route'].search([
            ('group_from_id', '=', current_group.id)
        ], order='sequence')
        
        if not routes:
            _logger.info("Không tìm thấy tuyến đường nào từ nhóm %s", current_group.name)
            return False
        
        # Tìm tuyến đường phù hợp với gói
        if package:
            package_routes = routes.filtered(lambda r: r.package_id and r.package_id.id == package.id)
            if package_routes:
                return package_routes[0].group_to_id
        
        # Tìm tuyến đường không có gói cụ thể
        general_routes = routes.filtered(lambda r: not r.package_id)
        if general_routes:
            return general_routes[0].group_to_id
        
        # Nếu không có tuyến đường nào phù hợp, trả về nhóm đầu tiên
        return routes[0].group_to_id

    # Thêm các phương thức mới
    def _compute_next_recommended_service(self):
        """Tính toán dịch vụ nên thực hiện tiếp theo"""
        for token in self:
            # Nếu là token song song và còn token khác chưa hoàn thành
            if token.is_parallel and token.parallel_token_ids:
                # Lấy các token song song ở trạng thái draft
                draft_tokens = token.parallel_token_ids.filtered(lambda t: t.state == 'draft')
                
                if draft_tokens:
                    # Tìm token tối ưu nhất
                    optimal_token = self._calculate_optimal_service(draft_tokens.ids)
                    if optimal_token:
                        token.next_recommended_service_id = optimal_token.service_id
                        continue
            
            # Nếu không phải trường hợp song song hoặc không tìm thấy token tối ưu
            token.next_recommended_service_id = False
    
    def _calculate_optimal_service(self, token_ids):
        """Tính toán dịch vụ tối ưu nhất để thực hiện tiếp theo"""
        tokens = self.browse(token_ids)
        
        if not tokens:
            return False
        
        # Trọng số cho các tiêu chí
        WEIGHT_MOVEMENT = 0.4    # Trọng số cho thời gian di chuyển
        WEIGHT_WAITING = 0.35     # Trọng số cho thời gian chờ đợi tại phòng
        WEIGHT_DURATION = 0.15    # Trọng số cho thời gian thực hiện dịch vụ
        WEIGHT_MEDICAL = 0.1     # Trọng số cho ưu tiên y tế
        
        best_token = False
        best_score = float('inf')  # Điểm càng thấp càng tốt
        
        # Lấy vị trí hiện tại (phòng hiện tại)
        current_location = self.room_id if self.room_id else None
        
        for token in tokens:
            # 1. Điểm di chuyển (dựa trên khoảng cách giữa các phòng)
            movement_score = self._calculate_distance_score(current_location, token.room_id) if current_location else 5
            
            # 2. Điểm thời gian chờ
            waiting_tokens = self.search_count([
                ('room_id', '=', token.room_id.id),
                ('state', '=', 'waiting')
            ])
            capacity = token.room_id.capacity if token.room_id.capacity > 0 else 1
            waiting_score = waiting_tokens / capacity * 10  # Chuẩn hóa 0-10
            
            # 3. Điểm thời gian thực hiện
            duration_score = token.service_id.average_duration / 10  # Chuẩn hóa, giả sử max 100 phút
            
            # 4. Điểm ưu tiên y tế (càng thấp càng ưu tiên)
            medical_priority = {
                'BLOOD': 1,  # Xét nghiệm máu ưu tiên cao nhất
                'XRAY': 3, 
                'ULTRA': 4,
                'DOC': 2,
                'VITAL': 5,
                'REG': 10
            }
            med_score = medical_priority.get(token.service_id.code, 5)
            
            # Tính tổng điểm (điểm thấp hơn = ưu tiên cao hơn)
            total_score = (
                WEIGHT_MOVEMENT * movement_score + 
                WEIGHT_WAITING * waiting_score + 
                WEIGHT_DURATION * duration_score +
                WEIGHT_MEDICAL * med_score
            )
            
            _logger.info(
                "Token %s - Di chuyển: %.2f, Chờ: %.2f, Thời gian: %.2f, Y tế: %.2f, Tổng: %.2f", 
                token.name, movement_score, waiting_score, duration_score, med_score, total_score
            )
            
            if total_score < best_score:
                best_score = total_score
                best_token = token
        
        return best_token
    
    def _calculate_distance_score(self, from_room, to_room):
        """Tính điểm khoảng cách giữa các phòng"""
        if not from_room or not to_room:
            return 5  # Giá trị mặc định
        
        if from_room.id == to_room.id:
            return 0  # Cùng phòng
        
        # Ma trận khoảng cách thực tế giữa các phòng
        distance_matrix = {
            # Format: ('from_code', 'to_code'): distance_value
            ('REG01', 'BLOOD01'): 2,
            ('REG01', 'XRAY01'): 4,
            ('REG01', 'UTR01'): 4,
            ('REG01', 'DOC01'): 3,
            ('REG01', 'DOC02'): 3,
            ('BLOOD01', 'XRAY01'): 3,
            ('BLOOD01', 'UTR01'): 2,
            ('BLOOD01', 'DOC01'): 4,
            ('BLOOD01', 'DOC02'): 4,
            ('XRAY01', 'UTR01'): 1,
            ('XRAY01', 'DOC01'): 3,
            ('XRAY01', 'DOC02'): 3,
            ('UTR01', 'DOC01'): 3,
            ('UTR01', 'DOC02'): 3,
            ('DOC01', 'DOC02'): 1,
            ('DOC01', 'PHARM01'): 2,
            ('DOC02', 'PHARM01'): 2,
        }
        
        # Tìm khoảng cách trong ma trận
        key = (from_room.code, to_room.code)
        reverse_key = (to_room.code, from_room.code)
        
        if key in distance_matrix:
            return distance_matrix[key]
        elif reverse_key in distance_matrix:
            return distance_matrix[reverse_key]
        else:
            # Nếu không tìm thấy trực tiếp, tìm đường đi gián tiếp (có thể triển khai thuật toán đường đi ngắn nhất)
            return 5  # Mặc định
    
    def _create_tokens_for_service_group(self, service_group, patient, origin_token, state='draft'):
        """Tạo token cho tất cả dịch vụ trong nhóm"""
        if not service_group or not patient:
            return self.env['queue.token']
        
        # Cập nhật nhóm dịch vụ hiện tại cho bệnh nhân
        patient.write({
            'current_service_group_id': service_group.id
        })
        
        created_tokens = self.env['queue.token']
        service_type = origin_token.service_type if origin_token else 'regular'
        health_check_batch_id = origin_token.health_check_batch_id.id if origin_token and origin_token.health_check_batch_id else False
        
        # Tạo token cho từng dịch vụ trong nhóm
        for service in service_group.service_ids:
            _logger.info("Tạo token cho dịch vụ %s trong nhóm %s", service.name, service_group.name)
            
            token_vals = {
                'patient_id': patient.id,
                'service_id': service.id,
                'service_group_id': service_group.id,
                'priority': origin_token.priority if origin_token else 0,
                'priority_id': origin_token.priority_id.id if origin_token and origin_token.priority_id else False,
                'emergency': origin_token.emergency if origin_token else False,
                'notes': _("Tự động tạo từ nhóm dịch vụ %s") % service_group.name,
                'origin_token_id': origin_token.id if origin_token else False,
                'is_parallel': True,
                'state': state,
                'service_type': service_type,
                'health_check_batch_id': health_check_batch_id,
            }
            
            new_token = self.create(token_vals)
            created_tokens += new_token
            _logger.info("Đã tạo token %s cho dịch vụ %s thuộc nhóm %s", 
                       new_token.name, service.name, service_group.name)
        
        # Liên kết các token song song với nhau
        if len(created_tokens) > 1:
            _logger.info("Liên kết %s token song song với nhau", len(created_tokens))
            for token in created_tokens:
                other_tokens = created_tokens - token
                token.write({
                    'parallel_token_ids': [(6, 0, other_tokens.ids)],
                })
        
        return created_tokens
    
    def action_complete_service(self):
        """Hoàn tất việc phục vụ token này"""
        for token in self:
            if token.state != 'in_progress':
                raise UserError(_("Chỉ có thể hoàn thành các token đang được phục vụ."))

            # Lưu trữ thông tin trước khi cập nhật
            current_service = token.service_id
            patient = token.patient_id
            package = patient.queue_package_id
            
            # Cập nhật trạng thái token và thời gian
            token.write({
                'state': 'completed',
                'end_time': fields.Datetime.now()
            })

            # Cập nhật thời gian phục vụ trung bình của dịch vụ
            if token.actual_duration > 0:
                current_service._update_average_duration(token.actual_duration)

            # Cập nhật dịch vụ đã hoàn thành cho bệnh nhân
            if patient and current_service:
                if 'completed_service_ids' in patient._fields:
                    patient.write({
                        'completed_service_ids': [(4, current_service.id)]
                    })

            # Xử lý logic tiếp theo dựa trên loại token và dịch vụ
            result = None
            
            # Kiểm tra nếu token này thuộc nhóm song song
            if token.is_parallel and token.service_group_id:
                # Xử lý hoàn thành token song song
                result = self._handle_parallel_token_completion(token, patient)
            else:
                # Lấy nhóm dịch vụ hiện tại của bệnh nhân
                current_group = patient.current_service_group_id
                
                # Nếu đang ở nhóm đăng ký và đo sinh hiệu
                if current_group and current_group.code == 'REG_VITAL':
                    # Kiểm tra xem nhóm này đã hoàn thành hết chưa
                    group_completed = self._check_service_group_completion(current_group, patient)
                    
                    if group_completed:
                        _logger.info("Nhóm REG_VITAL đã hoàn thành. Tìm nhóm tiếp theo")
                        
                        # Đối với bệnh nhân VIP, tạo token song song cho nhóm xét nghiệm
                        if patient.is_vip:
                            parallel_group = self.env['queue.service.group'].search([
                                ('code', '=', 'PARALLEL_TESTS')
                            ], limit=1)
                            
                            if parallel_group:
                                result = self._handle_vip_service_completion(token, patient, parallel_group)
                        else:
                            # Đối với bệnh nhân thường, tiếp tục quy trình bình thường
                            result = self._process_single_service_completion(token, current_service, patient, package)
                    else:
                        # Chưa hoàn thành cả nhóm, tìm dịch vụ tiếp theo trong cùng nhóm
                        next_service = self._get_next_service_in_group(current_group, current_service)
                        if next_service:
                            new_token = self.create({
                                'patient_id': patient.id,
                                'service_id': next_service.id,
                                'service_group_id': current_group.id,
                                'priority': token.priority,
                                'priority_id': token.priority_id.id if token.priority_id else False,
                                'emergency': token.emergency,
                                'notes': _("Tự động tạo để hoàn thành nhóm dịch vụ %s") % current_group.name,
                                'origin_token_id': token.id,
                                'service_type': token.service_type,
                                'health_check_batch_id': token.health_check_batch_id.id if token.health_check_batch_id else False,
                                'state': 'waiting',
                            })
                            
                            result = {
                                'type': 'ir.actions.client',
                                'tag': 'display_notification',
                                'params': {
                                    'title': _('Dịch vụ tiếp theo'),
                                    'message': _('Vui lòng hướng dẫn bệnh nhân đến %s cho dịch vụ %s') 
                                            % (new_token.room_id.name, new_token.service_id.name),
                                    'sticky': True,
                                    'type': 'info',
                                }
                            }
                else:
                    # Xử lý hoàn thành dịch vụ đơn lẻ
                    result = self._process_single_service_completion(token, current_service, patient, package)

            # Thông báo cho màn hình phòng về sự thay đổi hàng đợi
            self._notify_queue_change(token.room_id)
            
            return result if result else {'type': 'ir.actions.act_window_close'}
    
    # Cập nhật hàm xử lý hoàn thành token song song
    def _handle_parallel_token_completion(self, token, patient):
        """Xử lý khi hoàn thành một token trong nhóm song song"""
        # Tìm các token song song khác chưa hoàn thành
        other_tokens = token.parallel_token_ids.filtered(lambda t: t.state == 'draft')
        
        if not other_tokens:
            # Kiểm tra xem tất cả token đã hoàn thành chưa
            all_completed = all(t.state == 'completed' for t in token.parallel_token_ids)
            
            if all_completed:
                # Đã hoàn thành tất cả token song song, tạo token cho bước tiếp theo
                _logger.info("Tất cả token song song đã hoàn thành, chuyển sang bước tiếp theo")
                return self._create_next_service_token(token, patient)
            
            # Có thể còn token đang thực hiện, không làm gì
            return None
        
        # Có token chưa hoàn thành, tìm token tối ưu tiếp theo
        next_token = self._calculate_optimal_service(other_tokens.ids)
        
        if next_token:
            # Kích hoạt token tiếp theo
            next_token.write({
                'state': 'waiting',
                'priority': next_token.priority + 1  # Tăng ưu tiên
            })
            
            # Thông báo hướng dẫn
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Dịch vụ tiếp theo'),
                    'message': _('Vui lòng hướng dẫn bệnh nhân đến %s cho dịch vụ %s (Token: %s)') 
                            % (next_token.room_id.name, next_token.service_id.name, next_token.name),
                    'sticky': True,
                    'type': 'info',
                }
            }
        
        return None
    
    # Trong _handle_registration_completion, cần sửa đổi để đặt một token là active và các token khác là pending
    def _handle_registration_completion(self, token, patient):
        """Xử lý khi hoàn thành đăng ký cho bệnh nhân"""
        # Tìm nhóm dịch vụ song song
        parallel_group = self.env['queue.service.group'].search([
            ('code', '=', 'PARALLEL_TESTS')
        ], limit=1)
        
        if not parallel_group:
            _logger.warning("Không tìm thấy nhóm dịch vụ song song với mã PARALLEL_TESTS")
            return None
        
        _logger.info("Tìm thấy nhóm dịch vụ song song: %s", parallel_group.name)
        
        # Tạo các token ở trạng thái draft thay vì waiting
        created_tokens = self._create_tokens_for_service_group(parallel_group, patient, token, state='draft')
        
        if not created_tokens:
            _logger.warning("Không thể tạo token song song")
            return None
        
        # Tính toán token tối ưu
        optimal_token = self._calculate_optimal_service(created_tokens.ids)
        
        if not optimal_token:
            # Nếu không tìm thấy token tối ưu, lấy token đầu tiên
            optimal_token = created_tokens[0]
        
        # Kích hoạt chỉ token tối ưu, các token khác giữ ở trạng thái draft
        for t in created_tokens:
            if t.id == optimal_token.id:
                t.write({
                    'state': 'waiting',
                    'priority': t.priority + 2  # Tăng priority để đảm bảo token này được ưu tiên
                })
            else:
                t.write({
                    'state': 'draft',  # Giữ các token khác ở trạng thái draft
                    'notes': t.notes + " - Chờ sau khi hoàn thành Xét Nghiệm " + optimal_token.service_id.name
                })
        
        # Thông báo hướng dẫn
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Dịch vụ đề xuất tiếp theo'),
                'message': _('Vui lòng hướng dẫn bệnh nhân đến %s cho dịch vụ %s (Token: %s)') 
                        % (optimal_token.room_id.name, optimal_token.service_id.name, optimal_token.name),
                'sticky': True,
                'type': 'info',
            }
        }
    
    def _create_next_service_token(self, completed_token, patient):
        """Tạo token cho dịch vụ tiếp theo sau khi hoàn thành nhóm dịch vụ song song"""
        # Tìm nhóm dịch vụ tiếp theo
        service_group = completed_token.service_group_id
        if not service_group:
            return None
        
        # Tìm tuyến đường từ nhóm hiện tại đến nhóm tiếp theo
        next_group = self._get_next_service_group(service_group, patient.queue_package_id)
        
        if not next_group:
            _logger.info("Không tìm thấy nhóm dịch vụ tiếp theo")
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Hoàn thành'),
                    'message': _('Đã hoàn thành tất cả các dịch vụ cho bệnh nhân %s') % patient.name,
                    'sticky': False,
                    'type': 'info',
                }
            }
        
        # Tạo token cho nhóm tiếp theo
        _logger.info("Tạo token cho nhóm dịch vụ tiếp theo: %s", next_group.name)
        # Kiểm tra xem nhóm tiếp theo có phải là nhóm song song không
        if len(next_group.service_ids) > 1:
            # Tạo token song song cho nhóm tiếp theo
            new_tokens = self._create_tokens_for_service_group(next_group, patient, completed_token, state='draft')
            
            if new_tokens:
                # Tìm token tối ưu để thực hiện đầu tiên
                optimal_token = self._calculate_optimal_service(new_tokens.ids)
                
                if optimal_token:
                    # Kích hoạt token đầu tiên
                    optimal_token.write({'state': 'waiting'})
                    
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': _('Dịch vụ tiếp theo'),
                            'message': _('Vui lòng hướng dẫn bệnh nhân đến %s cho dịch vụ %s') 
                                      % (optimal_token.room_id.name, optimal_token.service_id.name),
                            'sticky': True,
                            'type': 'info',
                        }
                    }
        else:
            # Tạo token đơn cho dịch vụ đầu tiên trong nhóm
            service = next_group.service_ids[0]
            
            new_token = self.create({
                'patient_id': patient.id,
                'service_id': service.id,
                'service_group_id': next_group.id,
                'priority': completed_token.priority,
                'priority_id': completed_token.priority_id.id if completed_token.priority_id else False,
                'emergency': completed_token.emergency,
                'notes': _("Tự động tạo sau khi hoàn thành nhóm dịch vụ %s") % service_group.name,
                'origin_token_id': completed_token.id,
                'service_type': completed_token.service_type,
                'health_check_batch_id': completed_token.health_check_batch_id.id if completed_token.health_check_batch_id else False,
                'state': 'waiting',
            })
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Dịch vụ tiếp theo'),
                    'message': _('Vui lòng hướng dẫn bệnh nhân đến %s cho dịch vụ %s') 
                              % (new_token.room_id.name, new_token.service_id.name),
                    'sticky': True,
                    'type': 'info',
                }
            }
        
        return None
    
    def _compute_wait_time(self):
        """Tính toán thời gian chờ ước tính dựa trên nhiều yếu tố"""
        for token in self:
            if token.state != 'waiting':
                token.estimated_wait_time = 0
                continue
            
            room = token.room_id
            if not room:
                token.estimated_wait_time = 0
                continue
            
            # Lấy tất cả token đang chờ của phòng này
            waiting_tokens = self.search([
                ('room_id', '=', room.id),
                ('state', '=', 'waiting'),
                ('position', '<', token.position)
            ])
            
            # Tính toán thời gian cơ bản
            avg_duration = token.service_id.average_duration
            base_wait_time = len(waiting_tokens) * avg_duration / room.capacity
            
            # Điều chỉnh theo đặt lịch và loại dịch vụ
            reservation = room.get_current_reservation()
            if reservation:
                if reservation.service_type != 'all' and reservation.service_type != token.service_type:
                    # Đặt lịch cho loại dịch vụ khác, tăng thời gian chờ
                    token.estimated_wait_time = base_wait_time * 2
                else:
                    # Đặt lịch đúng loại dịch vụ, điều chỉnh theo công suất
                    token.estimated_wait_time = base_wait_time * (100 / reservation.capacity_percentage)
            else:
                # Không có đặt lịch, sử dụng thời gian cơ bản
                token.estimated_wait_time = base_wait_time
    
    def _recalculate_queue_positions(self, room_id):
        """Tính lại vị trí trong hàng đợi cho tất cả token của phòng"""
        waiting_tokens = self.search([
            ('room_id', '=', room_id),
            ('state', '=', 'waiting')
        ])
        
        # Sắp xếp token theo ưu tiên, loại dịch vụ và thời gian tạo
        # Ưu tiên cao hơn, emergency và health_check có quyền ưu tiên
        sorted_tokens = waiting_tokens.sorted(
            key=lambda r: (
                -r.emergency,
                -(r.service_type == 'emergency'),  # emergency service first
                -(r.service_type == 'health_check'),  # then health check
                -r.priority,
                r.create_date
            )
        )
        
        # Cập nhật vị trí
        for position, token in enumerate(sorted_tokens, 1):
            token.position = position

    # Phải thêm phương thức _process_single_service_completion nếu chưa có
    def _process_single_service_completion(self, token, current_service, patient, package):
        """Xử lý hoàn thành dịch vụ theo cách thông thường (không theo nhóm)"""
        # Tìm tuyến đường dịch vụ tiếp theo
        routes = self.env['queue.service.route'].search([
            ('service_from_id', '=', current_service.id)
        ], order='sequence')
        _logger.info("Tìm thấy %d tuyến đường cho dịch vụ %s", len(routes), current_service.name)
       
        # Biến để lưu dịch vụ tiếp theo
        next_service = False
        
        if routes:
            # Hiển thị thông tin về các tuyến đường tìm thấy
            for route in routes:
                _logger.info("Tuyến đường: %s -> %s, Gói: %s", 
                            route.service_from_id.name, 
                            route.service_to_id.name, 
                            route.package_id and route.package_id.name or "Chung")
            
            # Tìm tuyến đường phù hợp với gói
            if package:
                package_routes = routes.filtered(lambda r: r.package_id and r.package_id.id == package.id)
                if package_routes:
                    next_service = package_routes[0].service_to_id
                    _logger.info("Sử dụng tuyến đường theo gói %s: %s -> %s", 
                                package.name, current_service.name, next_service.name)
            
            # Nếu không tìm thấy tuyến đường theo gói, tìm tuyến đường chung
            if not next_service:
                general_routes = routes.filtered(lambda r: not r.package_id)
                if general_routes:
                    next_service = general_routes[0].service_to_id
                    _logger.info("Sử dụng tuyến đường chung: %s -> %s", 
                                current_service.name, next_service.name)
                else:
                    # Sử dụng tuyến đường đầu tiên nếu không có tuyến nào phù hợp
                    next_service = routes[0].service_to_id
                    _logger.info("Sử dụng tuyến đường đầu tiên: %s -> %s", 
                                current_service.name, next_service.name)
        
        # Nếu không có tuyến đường, hiển thị cảnh báo
        if not routes:
            token.message_post(
                body=_(
                    "Không tìm thấy tuyến đường dịch vụ từ %s. "
                    "Vui lòng kiểm tra cấu hình tuyến đường dịch vụ."
                ) % current_service.name,
                subject=_("Cảnh báo: Thiếu tuyến đường dịch vụ")
            )
        
        # Tạo token mới nếu có dịch vụ tiếp theo
        if next_service:
            _logger.info("Tạo token mới cho dịch vụ tiếp theo: %s", next_service.name)
            new_token = self.create({
                'patient_id': patient.id,
                'service_id': next_service.id,
                'priority': token.priority,
                'priority_id': token.priority_id.id if token.priority_id else False,
                'emergency': token.emergency,
                'notes': _("Tự động tạo sau khi hoàn thành dịch vụ %s") % current_service.name,
                'origin_token_id': token.id,
                'service_type': token.service_type,
                'health_check_batch_id': token.health_check_batch_id.id if token.health_check_batch_id else False,
                'state': 'waiting',
            })
            _logger.info("Đã tạo token mới: %s", new_token.name)
            return new_token
        else:
            _logger.info("Không có dịch vụ tiếp theo cho token %s", token.name)
            # Thông báo cho người dùng
            if routes:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Hoàn thành dịch vụ'),
                        'message': _('Không tìm thấy dịch vụ tiếp theo phù hợp. Vui lòng kiểm tra cấu hình tuyến đường.'),
                        'sticky': True,
                        'type': 'warning',
                    }
                }
            else:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Hoàn thành dịch vụ'),
                        'message': _('Đã hoàn thành dịch vụ cuối cùng cho bệnh nhân %s') % patient.name,
                        'sticky': False,
                        'type': 'info',
                    }
                }
            
    def _get_next_service_in_group(self, service_group, current_service):
        """Lấy dịch vụ tiếp theo trong cùng nhóm dịch vụ"""
        if not service_group or not current_service:
            return False
        
        all_services = service_group.service_ids
        # Sắp xếp dịch vụ theo sequence
        sorted_services = all_services.sorted(key=lambda r: r.sequence)
        
        # Tìm vị trí của dịch vụ hiện tại
        current_index = -1
        for i, service in enumerate(sorted_services):
            if service.id == current_service.id:
                current_index = i
                break
        
        # Kiểm tra nếu có dịch vụ tiếp theo
        if current_index >= 0 and current_index < len(sorted_services) - 1:
            return sorted_services[current_index + 1]
        
        return False

    def _handle_vip_service_completion(self, token, patient, parallel_group):
        """Xử lý đặc biệt cho bệnh nhân VIP sau khi hoàn thành nhóm đăng ký"""
        _logger.info("Bệnh nhân VIP %s đã hoàn thành nhóm đăng ký, tạo token song song", patient.name)
        
        # Cập nhật nhóm dịch vụ hiện tại cho bệnh nhân
        patient.write({
            'current_service_group_id': parallel_group.id
        })
        
        # Tạo các token ở trạng thái draft
        created_tokens = self._create_tokens_for_service_group(parallel_group, patient, token, state='draft')
        
        if not created_tokens:
            _logger.warning("Không thể tạo token song song")
            return None
        
        # Tính toán token tối ưu
        optimal_token = self._calculate_optimal_service(created_tokens.ids)
        
        if not optimal_token:
            # Nếu không tìm thấy token tối ưu, lấy token đầu tiên
            optimal_token = created_tokens[0]
        
        # Kích hoạt chỉ token tối ưu, các token khác giữ ở trạng thái draft
        for t in created_tokens:
            if t.id == optimal_token.id:
                t.write({
                    'state': 'waiting',
                    'priority': t.priority + 2  # Tăng priority để đảm bảo token này được ưu tiên
                })
            else:
                t.write({
                    'state': 'draft',  # Giữ các token khác ở trạng thái draft
                    'notes': t.notes + " - Chờ sau khi hoàn thành Xét Nghiệm " + optimal_token.service_id.name
                })
        
        # Thông báo hướng dẫn
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Dịch vụ đề xuất tiếp theo'),
                'message': _('Vui lòng hướng dẫn bệnh nhân đến %s cho dịch vụ %s (Token: %s)') 
                        % (optimal_token.room_id.name, optimal_token.service_id.name, optimal_token.name),
                'sticky': True,
                'type': 'info',
            }
        }