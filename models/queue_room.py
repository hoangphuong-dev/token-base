# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from datetime import time


class QueueRoom(models.Model):
    _name = 'queue.room'
    _description = 'Phòng Phục Vụ'
    
    name = fields.Char(string='Tên Phòng', required=True)
    code = fields.Char(string='Mã Phòng', required=True)
    service_id = fields.Many2one('queue.service', string='Dịch Vụ', required=True)
    capacity = fields.Integer(string='Công Suất', default=1, 
        help="Số lượng bệnh nhân có thể được phục vụ đồng thời")
    current_queue = fields.One2many('queue.token', 'room_id', string='Hàng Đợi Hiện Tại',
        domain=[('state', '=', 'waiting')])
    queue_length = fields.Integer(string='Độ Dài Hàng Đợi', compute='_compute_queue_length')
    estimated_wait_time = fields.Float(string='Thời Gian Chờ Ước Tính (phút)', compute='_compute_wait_time')
    active = fields.Boolean(string='Hoạt Động', default=True)
    state = fields.Selection([
        ('open', 'Mở'),
        ('closed', 'Đóng'),
        ('maintenance', 'Bảo Trì')
    ], string='Trạng Thái', default='open')
    color = fields.Integer(string='Màu', default=0)
    reservation_ids = fields.One2many('queue.room.reservation', 'room_id', string='Lịch Đặt Phòng')

    
    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'Mã phòng phải là duy nhất!')
    ]
    
    @api.depends('current_queue')
    def _compute_queue_length(self):
        """Tính toán độ dài hàng đợi hiện tại"""
        for room in self:
            room.queue_length = len(room.current_queue)
    
    @api.depends('queue_length', 'service_id.average_duration')
    def _compute_wait_time(self):
        """Tính toán thời gian chờ ước tính cho bệnh nhân mới"""
        for room in self:
            avg_duration = room.service_id.average_duration
            # Công thức: Số người đợi * Thời gian trung bình / Công suất phòng
            room.estimated_wait_time = room.queue_length * avg_duration / room.capacity
    
    def action_open_room(self):
        """Mở phòng cho phục vụ"""
        for room in self:
            room.state = 'open'
    
    def action_close_room(self):
        """Đóng phòng"""
        for room in self:
            room.state = 'closed'
            
            # Thông báo cho nhân viên về việc đóng phòng
            self.env['mail.message'].create({
                'model': 'queue.room',
                'res_id': room.id,
                'message_type': 'notification',
                'body': _(f"Phòng {room.name} đã được đóng. Vui lòng phân công lại bệnh nhân nếu cần.")
            })
    
    def action_maintenance(self):
        """Đặt phòng vào trạng thái bảo trì"""
        for room in self:
            room.state = 'maintenance'
    
    def action_view_tokens(self):
        """Xem tất cả token cho phòng này"""
        self.ensure_one()
        return {
            'name': _('Token'),
            'view_mode': 'list,form',
            'res_model': 'queue.token',
            'domain': [('room_id', '=', self.id)],
            'type': 'ir.actions.act_window',
            'context': {'default_room_id': self.id}
        }
    
    def get_current_reservation(self):
        """Lấy đặt lịch hiện tại của phòng"""
        self.ensure_one()
        now = fields.Datetime.now()
        return self.env['queue.room.reservation'].search([
            ('room_id', '=', self.id),
            ('start_time', '<=', now),
            ('end_time', '>=', now),
            ('active', '=', True),
        ], limit=1)
    
    def get_available_capacity(self, service_type=False):
        """Tính toán công suất khả dụng cho loại dịch vụ cụ thể"""
        self.ensure_one()
        
        # Kiểm tra thời gian hiện tại
        now = fields.Datetime.now()
        current_time = now.time()
        
        # Lấy thông tin đặt lịch hiện tại
        reservation = self.get_current_reservation()
        
        # Khung giờ dành riêng cho khám sức khỏe định kỳ
        morning_start = time(7, 30)
        morning_end = time(11, 30)
        
        # Khung giờ chiều phục vụ đa dạng nhưng có tỷ lệ dành riêng
        afternoon_start = time(13, 30) 
        afternoon_end = time(16, 30)
        
        # Xử lý theo khung giờ và loại dịch vụ
        if morning_start <= current_time <= morning_end:
            # Buổi sáng chỉ phục vụ khám sức khỏe định kỳ
            if service_type == 'health_check':
                return self.capacity
            else:
                # Các dịch vụ khác được phục vụ hạn chế trong khung giờ này
                return self.capacity * 0.2  # 20% công suất cho dịch vụ khác
        
        elif afternoon_start <= current_time <= afternoon_end:
            # Buổi chiều phục vụ đa dạng nhưng ưu tiên khám thường
            if service_type == 'health_check':
                return self.capacity * 0.3  # 30% công suất
            else:
                return self.capacity * 0.7  # 70% công suất
        
        else:
            # Thời gian khác trong ngày không có đặt lịch đặc biệt
            if reservation:
                if reservation.service_type == 'all' or reservation.service_type == service_type:
                    return self.capacity * reservation.capacity_percentage / 100
                else:
                    return self.capacity * 0.3  # 30% cho các dịch vụ không thuộc đặt lịch
            
            return self.capacity  # Trả về toàn bộ công suất`