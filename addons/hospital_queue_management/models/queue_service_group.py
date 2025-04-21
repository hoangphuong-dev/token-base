from odoo import models, fields


class QueueServiceGroup(models.Model):
    _name = 'queue.service.group'
    _description = 'Nhóm Dịch Vụ Y Tế'
    _order = 'sequence'

    name = fields.Char(string='Tên Nhóm', required=True)
    code = fields.Char(string='Mã Nhóm', required=True)
    sequence = fields.Integer(string='Thứ Tự', default=10)
    service_ids = fields.Many2many('queue.service', string='Dịch Vụ Trong Nhóm')
    description = fields.Text(string='Mô Tả')
    is_required = fields.Boolean(string='Bắt Buộc', default=True,
                                 help="Nếu đánh dấu, tất cả dịch vụ trong nhóm phải hoàn thành. Nếu không, hoàn thành 1 dịch vụ có thể đủ để chuyển sang nhóm tiếp theo.")
    completion_policy = fields.Selection([
        ('all', 'Hoàn Thành Tất Cả'),
        ('any', 'Hoàn Thành Bất Kỳ'),
        ('custom', 'Tùy Chỉnh')
    ], string='Chính Sách Hoàn Thành', default='all')
    custom_rule = fields.Text(string='Quy Tắc Tùy Chỉnh',
                              help="Python expression để đánh giá điều kiện hoàn thành. Biến khả dụng: completed_services, total_services")
    active = fields.Boolean(string='Hoạt Động', default=True)

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'Mã nhóm phải là duy nhất!')
    ]
