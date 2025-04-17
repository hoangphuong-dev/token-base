# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

class QueueService(models.Model):
    _name = 'queue.service'
    _description = 'Dịch Vụ Y Tế'
    
    name = fields.Char(string='Tên Dịch Vụ', required=True)
    code = fields.Char(string='Mã Dịch Vụ', required=True)
    sequence = fields.Integer(string='Thứ Tự', default=10)
    active = fields.Boolean(string='Hoạt Động', default=True)
    service_type = fields.Selection([
        ('registration', 'Đăng Ký'),
        ('vitals', 'Dấu Hiệu Sinh Tồn'),
        ('lab', 'Xét Nghiệm'),
        ('imaging', 'Chẩn Đoán Hình Ảnh'),
        ('consultation', 'Khám Bệnh'),
        ('specialty', 'Khám Chuyên Khoa'),
        ('other', 'Khác')
    ], string='Loại Dịch Vụ', required=True)
    description = fields.Text(string='Mô Tả')
    average_duration = fields.Float(string='Thời Gian Trung Bình (phút)', default=10.0)
    duration_count = fields.Integer(string='Số Lượt Tính Thời Gian', default=0)
    rooms_ids = fields.One2many('queue.room', 'service_id', string='Phòng Phục Vụ')
    
    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'Mã dịch vụ phải là duy nhất!')
    ]
    
    def _update_average_duration(self, duration):
        """
        Cập nhật thời gian trung bình của dịch vụ
        
        Tham số:
            duration (float): Thời gian thực tế của lần phục vụ mới (phút)
        """
        for service in self:
            current_avg = service.average_duration
            current_count = service.duration_count
            
            # Tính trung bình cộng theo công thức: ((avg_cũ * số_lượt_cũ) + giá_trị_mới) / (số_lượt_cũ + 1)
            new_count = current_count + 1
            new_avg = ((current_avg * current_count) + duration) / new_count
            
            service.write({
                'average_duration': new_avg,
                'duration_count': new_count
            })

class QueueServiceGroupRoute(models.Model):
    _name = 'queue.service.group.route'
    _description = 'Tuyến Đường Nhóm Dịch Vụ'
    
    name = fields.Char(string='Tên Tuyến', compute='_compute_name', store=True)
    group_from_id = fields.Many2one('queue.service.group', string='Từ Nhóm Dịch Vụ', required=True)
    group_to_id = fields.Many2one('queue.service.group', string='Đến Nhóm Dịch Vụ', required=True)
    condition = fields.Text(string='Điều Kiện Chuyển')
    sequence = fields.Integer(string='Độ Ưu Tiên', default=10)
    package_id = fields.Many2one('queue.package', string='Gói Dịch Vụ Cụ Thể')
    
    @api.depends('group_from_id', 'group_to_id')
    def _compute_name(self):
        for route in self:
            if route.group_from_id and route.group_to_id:
                route.name = f"{route.group_from_id.name} → {route.group_to_id.name}"
            else:
                route.name = _("Tuyến Nhóm Mới")

class QueueServiceRoute(models.Model):
    """
    Model này định nghĩa các tuyến đường (route) giữa các dịch vụ
    Ví dụ: Sau khi Đăng Ký -> đi tới Đo Dấu Hiệu Sinh Tồn -> đi tới Xét Nghiệm...
    """
    _name = 'queue.service.route'
    _description = 'Tuyến Đường Dịch Vụ'
    
    name = fields.Char(string='Tên Tuyến', compute='_compute_name', store=True)
    service_from_id = fields.Many2one('queue.service', string='Từ Dịch Vụ', required=True)
    service_to_id = fields.Many2one('queue.service', string='Đến Dịch Vụ', required=True)
    condition = fields.Text(string='Điều Kiện Chuyển', 
        help="Biểu thức Python để xác định liệu tuyến đường này có nên được sử dụng không")
    sequence = fields.Integer(string='Độ Ưu Tiên', default=10,
        help="Số thấp hơn có độ ưu tiên cao hơn khi có nhiều tuyến có thể áp dụng")
    package_id = fields.Many2one('queue.package', string='Gói Dịch Vụ Cụ Thể',
        help="Nếu được đặt, tuyến đường này chỉ áp dụng cho gói dịch vụ này")
    
    @api.model
    def init_demo_routes(self):
        """Khởi tạo lại tất cả các tuyến đường dịch vụ mẫu"""
        # Tìm các dịch vụ theo tên
        service_names = {
            'REG': 'Đăng ký',
            'VITAL': 'Đo Sinh Hiệu',
            'BLOOD': 'Xét nhiệm máu',
            'XRAY': 'X-Quang',
            'ULTRA': 'Siêu âm',  # Thêm Siêu âm vào danh sách
            'DOC': 'Khám bác sĩ',
            'PHARM': 'Nhận thuốc'
        }
        
        services = {}
        for code, name in service_names.items():
            service = self.env['queue.service'].search([('name', '=', name)], limit=1)
            if service:
                services[code] = service.id
            else:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Lỗi'),
                        'message': _('Không tìm thấy dịch vụ với tên %s') % name,
                        'sticky': True,
                        'type': 'danger',
                    }
                }
        
        # Tìm các gói dịch vụ
        packages = {}
        for code in ['basic', 'standard']:
            package = self.env['queue.package'].search([('code', '=', code)], limit=1)
            if package:
                packages[code] = package.id
            else:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Lỗi'),
                        'message': _('Không tìm thấy gói dịch vụ với mã %s') % code,
                        'sticky': True,
                        'type': 'danger',
                    }
                }
        
        # Xóa tất cả các tuyến đường hiện có
        existing_routes = self.search([])
        if existing_routes:
            existing_routes.unlink()
        
        # Danh sách các tuyến đường cần tạo
        routes_data = [
            # Tuyến đường chung cho bắt đầu quy trình
            {'from': 'REG', 'to': 'VITAL', 'package': False, 'sequence': 10},
            {'from': 'VITAL', 'to': 'BLOOD', 'package': False, 'sequence': 10},
            {'from': 'BLOOD', 'to': 'XRAY', 'package': False, 'sequence': 10},
            
            # Tuyến đường cho gói cơ bản
            {'from': 'XRAY', 'to': 'DOC', 'package': 'basic', 'sequence': 10},
            
            # Tuyến đường cho gói tiêu chuẩn
            {'from': 'XRAY', 'to': 'ULTRA', 'package': 'standard', 'sequence': 10},
            {'from': 'ULTRA', 'to': 'DOC', 'package': 'standard', 'sequence': 10},
            
            # Tuyến đường cuối cho tất cả các gói
            {'from': 'DOC', 'to': 'PHARM', 'package': False, 'sequence': 10},
        ]
        
        # Tạo các tuyến đường
        created_routes = []
        for route_data in routes_data:
            route_vals = {
                'service_from_id': services[route_data['from']],
                'service_to_id': services[route_data['to']],
                'sequence': route_data['sequence'],
            }
            
            if route_data['package']:
                route_vals['package_id'] = packages[route_data['package']]
            
            created_route = self.create(route_vals)
            created_routes.append(created_route)
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Thành công'),
                'message': _('Đã khởi tạo %s tuyến đường dịch vụ') % len(created_routes),
                'sticky': False,
                'type': 'success',
            }
        }
    
    @api.depends('service_from_id', 'service_to_id')
    def _compute_name(self):
        """Tạo tên tuyến đường từ tên các dịch vụ liên quan"""
        for route in self:
            if route.service_from_id and route.service_to_id:
                route.name = f"{route.service_from_id.name} → {route.service_to_id.name}"
            else:
                route.name = _("Tuyến Mới")