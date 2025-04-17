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
        ('draft', 'Nháp'),
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

    @api.model_create_multi
    def create(self, vals):
        """
        Ghi đè phương thức create để tạo mã token tự động và thực hiện quy trình phân phối
        Quy trình:
        1. Tạo mã token
        2. Tính toán mức ưu tiên dựa trên thông tin bệnh nhân
        3. Chỉ định phòng bằng thuật toán hash
        4. Thêm vào hàng đợi và sắp xếp theo ưu tiên
        """
        if vals.get('name', _('New')) == _('New'):
            vals['name'] = self.env['ir.sequence'].next_by_code('queue.token') or _('New')

        token = super(QueueToken, self).create(vals)

        # Tính toán mức ưu tiên dựa trên thông tin bệnh nhân
        token._calculate_priority()

        # Chỉ định phòng bằng thuật toán hash
        token._assign_room_by_hash()

        # Thêm vào hàng đợi và sắp xếp
        token._add_to_queue_and_sort()

        return token

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
            if token.state == 'draft':
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

    def action_complete_service(self):
        """Hoàn tất việc phục vụ token này"""
        for token in self:
            if token.state != 'in_progress':
                raise UserError(_("Chỉ có thể hoàn thành các token đang được phục vụ."))

            # Lưu trữ thông tin trước khi cập nhật
            current_service = token.service_id
            patient = token.patient_id
            package = patient.queue_package_id
            
            _logger.info("Hoàn thành token %s, dịch vụ: %s, gói: %s", 
                        token.name, 
                        current_service.name, 
                        package and package.name or "Không có")
            
            # Cập nhật trạng thái token
            token.write({
                'state': 'completed',
                'end_time': fields.Datetime.now()
            })

            # Cập nhật thời gian phục vụ trung bình của dịch vụ
            if token.actual_duration > 0:
                current_service._update_average_duration(token.actual_duration)

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
                    'priority_id': token.priority_id.id,
                    'emergency': token.emergency,
                    'notes': _("Tự động tạo sau khi hoàn thành dịch vụ %s") % current_service.name,
                })
                _logger.info("Đã tạo token mới: %s", new_token.name)
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

    # Cập nhật phương thức create để gửi thông báo khi tạo token mới
    @api.model
    def create(self, vals):
        # Phần code ban đầu giữ nguyên
        token = super(QueueToken, self).create(vals)
        token._calculate_priority()
        token._assign_room_by_hash()
        token._add_to_queue_and_sort()

        # Thêm phần gửi thông báo
        token._send_notifications('new_token')

        return token

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