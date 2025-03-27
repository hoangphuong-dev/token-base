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
    
    @api.depends('service_from_id', 'service_to_id')
    def _compute_name(self):
        """Tạo tên tuyến đường từ tên các dịch vụ liên quan"""
        for route in self:
            if route.service_from_id and route.service_to_id:
                route.name = f"{route.service_from_id.name} → {route.service_to_id.name}"
            else:
                route.name = _("Tuyến Mới")