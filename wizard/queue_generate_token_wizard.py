# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError

class QueueGenerateTokenWizard(models.TransientModel):
    _name = 'queue.generate.token.wizard'
    _description = 'Tạo Token Hàng Loạt'
    
    patient_ids = fields.Many2many('res.partner', string='Bệnh Nhân', domain=[('is_patient', '=', True)], required=True)
    service_id = fields.Many2one('queue.service', string='Dịch Vụ', required=True)
    priority_id = fields.Many2one('queue.priority', string='Mức Ưu Tiên')
    emergency = fields.Boolean(string='Khẩn Cấp', default=False)
    notes = fields.Text(string='Ghi Chú')
    assign_room = fields.Boolean(string='Chỉ Định Phòng Tự Động', default=True)
    room_id = fields.Many2one('queue.room', string='Phòng Chỉ Định')
    
    @api.onchange('service_id')
    def _onchange_service_id(self):
        """Cập nhật miền cho phòng khi thay đổi dịch vụ"""
        if self.service_id:
            return {'domain': {'room_id': [('service_id', '=', self.service_id.id), ('state', '=', 'open')]}}
        return {'domain': {'room_id': []}}
    
    def action_generate_tokens(self):
        """Tạo token cho các bệnh nhân đã chọn"""
        self.ensure_one()
        
        if not self.patient_ids:
            raise UserError(_("Vui lòng chọn ít nhất một bệnh nhân."))
            
        if not self.assign_room and not self.room_id:
            raise UserError(_("Vui lòng chọn phòng chỉ định hoặc bật tính năng chỉ định phòng tự động."))
            
        tokens_created = []
        
        for patient in self.patient_ids:
            # Tạo token
            vals = {
                'patient_id': patient.id,
                'service_id': self.service_id.id,
                'emergency': self.emergency,
                'notes': self.notes,
            }
            
            if self.priority_id:
                vals['priority_id'] = self.priority_id.id
                
            if not self.assign_room and self.room_id:
                vals['room_id'] = self.room_id.id
                
            token = self.env['queue.token'].create(vals)
            tokens_created.append(token.id)
            
        # Hiển thị thông báo thành công
        message = _(f"Đã tạo {len(tokens_created)} token thành công.")
        
        # Quay lại danh sách token đã tạo
        return {
            'name': _('Token Đã Tạo'),
            'view_mode': 'list,form',
            'res_model': 'queue.token',
            'domain': [('id', 'in', tokens_created)],
            'type': 'ir.actions.act_window',
            'target': 'current',
            'context': {'message': message}
        }