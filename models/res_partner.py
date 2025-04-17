# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from datetime import date

class ResPartner(models.Model):
    _inherit = 'res.partner'
    
    is_patient = fields.Boolean(string='Là Bệnh Nhân', default=False)
    date_of_birth = fields.Date(string='Ngày Sinh')
    age = fields.Integer(string='Tuổi', compute='_compute_age', store=True)
    gender = fields.Selection([
        ('male', 'Nam'),
        ('female', 'Nữ'),
        ('other', 'Khác')
    ], string='Giới Tính')
    is_pregnant = fields.Boolean(string='Mang Thai', default=False)
    is_disabled = fields.Boolean(string='Khuyết Tật', default=False)
    has_urgent_condition = fields.Boolean(string='Tình Trạng Cấp Thiết', default=False)
    is_vip = fields.Boolean(string='VIP', default=False)
    doctor_assigned_priority = fields.Boolean(string='Ưu Tiên Chỉ Định Bác Sĩ', default=False)
    queue_package_id = fields.Many2one('queue.package', string='Gói Khám Sức Khỏe')
    queue_history_ids = fields.One2many('queue.token', 'patient_id', string='Lịch Sử Khám')
    queue_history_count = fields.Integer(string='Số lượng token', compute='_compute_queue_history_count')
    current_service_group_id = fields.Many2one('queue.service.group', string='Nhóm Dịch Vụ Hiện Tại')
    completed_service_ids = fields.Many2many('queue.service', 'partner_completed_service_rel', 
                                          string='Dịch Vụ Đã Hoàn Thành', 
                                          help="Dịch vụ đã hoàn thành trong lần khám hiện tại")

    @api.depends('date_of_birth')
    def _compute_age(self):
        """Tính tuổi từ ngày sinh"""
        for partner in self:
            if partner.date_of_birth:
                today = date.today()
                born = partner.date_of_birth
                partner.age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
            else:
                partner.age = 0

    @api.depends('queue_history_ids')
    def _compute_queue_history_count(self):
        """Đếm số lượng token đã cấp cho bệnh nhân"""
        for partner in self:
            partner.queue_history_count = len(partner.queue_history_ids)