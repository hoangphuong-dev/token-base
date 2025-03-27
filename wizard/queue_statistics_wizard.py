# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from datetime import datetime, timedelta

class QueueStatisticsWizard(models.TransientModel):
    _name = 'queue.statistics.wizard'
    _description = 'Wizard Báo Cáo Thống Kê Hàng Đợi'
    
    date_from = fields.Date(string='Từ Ngày', default=lambda self: fields.Date.today() - timedelta(days=30))
    date_to = fields.Date(string='Đến Ngày', default=lambda self: fields.Date.today())
    service_ids = fields.Many2many('queue.service', string='Dịch Vụ')
    room_ids = fields.Many2many('queue.room', string='Phòng')
    report_type = fields.Selection([
        ('summary', 'Tổng Quan'),
        ('detailed', 'Chi Tiết'),
        ('waiting_time', 'Thời Gian Chờ'),
        ('service_time', 'Thời Gian Phục Vụ')
    ], string='Loại Báo Cáo', default='summary')
    group_by = fields.Selection([
        ('day', 'Theo Ngày'),
        ('week', 'Theo Tuần'),
        ('month', 'Theo Tháng'),
        ('service', 'Theo Dịch Vụ'),
        ('room', 'Theo Phòng')
    ], string='Nhóm Theo', default='day')
    
    def action_generate_report(self):
        """Tạo báo cáo thống kê dựa trên các tiêu chí đã chọn"""
        self.ensure_one()
        
        data = {
            'date_from': self.date_from,
            'date_to': self.date_to,
            'service_ids': self.service_ids.ids,
            'room_ids': self.room_ids.ids,
            'report_type': self.report_type,
            'group_by': self.group_by,
            'wizard_id': self.id,
        }
        
        # Xác định loại báo cáo để hiển thị
        if self.report_type == 'summary':
            return self._generate_summary_report(data)
        elif self.report_type == 'detailed':
            return self._generate_detailed_report(data)
        elif self.report_type == 'waiting_time':
            return self._generate_waiting_time_report(data)
        elif self.report_type == 'service_time':
            return self._generate_service_time_report(data)
        
        return {'type': 'ir.actions.act_window_close'}
    
    def _generate_summary_report(self, data):
        """Tạo báo cáo tổng quan"""
        return {
            'type': 'ir.actions.report',
            'report_name': 'hospital_queue_management.report_queue_summary',
            'report_type': 'qweb-pdf',
            'data': data,
        }
    
    def _generate_detailed_report(self, data):
        """Tạo báo cáo chi tiết"""
        return {
            'type': 'ir.actions.report',
            'report_name': 'hospital_queue_management.report_queue_detailed',
            'report_type': 'qweb-pdf',
            'data': data,
        }
    
    def _generate_waiting_time_report(self, data):
        """Tạo báo cáo thời gian chờ"""
        return {
            'type': 'ir.actions.report',
            'report_name': 'hospital_queue_management.report_queue_waiting_time',
            'report_type': 'qweb-pdf',
            'data': data,
        }
    
    def _generate_service_time_report(self, data):
        """Tạo báo cáo thời gian phục vụ"""
        return {
            'type': 'ir.actions.report',
            'report_name': 'hospital_queue_management.report_queue_service_time',
            'report_type': 'qweb-pdf',
            'data': data,
        }
    
    @api.model
    def get_report_data(self, data):
        """Lấy dữ liệu báo cáo dựa trên các tiêu chí đã chọn"""
        date_from = data.get('date_from')
        date_to = data.get('date_to')
        service_ids = data.get('service_ids', [])
        room_ids = data.get('room_ids', [])
        report_type = data.get('report_type', 'summary')
        group_by = data.get('group_by', 'day')
        
        domain = [
            ('create_date', '>=', date_from),
            ('create_date', '<=', date_to + ' 23:59:59')
        ]
        
        if service_ids:
            domain.append(('service_id', 'in', service_ids))
        
        if room_ids:
            domain.append(('room_id', 'in', room_ids))
        
        # Lấy dữ liệu token
        tokens = self.env['queue.token'].search(domain)
        
        # Tính toán dữ liệu thống kê
        result = {}
        
        if report_type == 'summary':
            result = self._calculate_summary_statistics(tokens, group_by)
        elif report_type == 'detailed':
            result = self._calculate_detailed_statistics(tokens, group_by)
        elif report_type == 'waiting_time':
            result = self._calculate_waiting_time_statistics(tokens, group_by)
        elif report_type == 'service_time':
            result = self._calculate_service_time_statistics(tokens, group_by)
        
        return result
    
    def _calculate_summary_statistics(self, tokens, group_by):
        """Tính toán thống kê tổng quan"""
        result = {
            'total_tokens': len(tokens),
            'waiting_tokens': len(tokens.filtered(lambda t: t.state == 'waiting')),
            'in_progress_tokens': len(tokens.filtered(lambda t: t.state == 'in_progress')),
            'completed_tokens': len(tokens.filtered(lambda t: t.state == 'completed')),
            'cancelled_tokens': len(tokens.filtered(lambda t: t.state == 'cancelled')),
            'emergency_tokens': len(tokens.filtered(lambda t: t.emergency)),
            'avg_waiting_time': 0,
            'avg_service_time': 0,
        }
        
        # Tính thời gian chờ và phục vụ trung bình
        completed_tokens = tokens.filtered(lambda t: t.state == 'completed' and t.actual_duration > 0)
        if completed_tokens:
            result['avg_service_time'] = sum(t.actual_duration for t in completed_tokens) / len(completed_tokens)
        
        # Nhóm dữ liệu theo tiêu chí
        grouped_data = []
        
        if group_by == 'day':
            # Nhóm theo ngày
            date_groups = {}
            for token in tokens:
                date_str = token.create_date.strftime('%Y-%m-%d')
                if date_str not in date_groups:
                    date_groups[date_str] = []
                date_groups[date_str].append(token)
            
            for date_str, group_tokens in date_groups.items():
                group_data = {
                    'name': date_str,
                    'total': len(group_tokens),
                    'completed': len([t for t in group_tokens if t.state == 'completed']),
                    'cancelled': len([t for t in group_tokens if t.state == 'cancelled']),
                    'emergency': len([t for t in group_tokens if t.emergency]),
                }
                grouped_data.append(group_data)
        
        elif group_by == 'service':
            # Nhóm theo dịch vụ
            service_groups = {}
            for token in tokens:
                service_id = token.service_id.id
                if service_id not in service_groups:
                    service_groups[service_id] = {
                        'name': token.service_id.name,
                        'tokens': []
                    }
                service_groups[service_id]['tokens'].append(token)
            
            for service_id, group_data in service_groups.items():
                group_tokens = group_data['tokens']
                grouped_data.append({
                    'name': group_data['name'],
                    'total': len(group_tokens),
                    'completed': len([t for t in group_tokens if t.state == 'completed']),
                    'cancelled': len([t for t in group_tokens if t.state == 'cancelled']),
                    'emergency': len([t for t in group_tokens if t.emergency]),
                })
        
        result['grouped_data'] = sorted(grouped_data, key=lambda x: x['name'])
        return result
    
    def _calculate_detailed_statistics(self, tokens, group_by):
        """Tính toán thống kê chi tiết"""
        # Tương tự như trên, nhưng chi tiết hơn
        # Có thể mở rộng theo yêu cầu
        return self._calculate_summary_statistics(tokens, group_by)
    
    def _calculate_waiting_time_statistics(self, tokens, group_by):
        """Tính toán thống kê thời gian chờ"""
        # Tính toán thống kê thời gian chờ theo nhóm
        result = {
            'total_tokens': len(tokens),
            'waiting_times': [],
        }
        
        # Xử lý dữ liệu thời gian chờ
        # (Cần thêm logic cho thống kê thời gian chờ)
        
        return result
    
    def _calculate_service_time_statistics(self, tokens, group_by):
        """Tính toán thống kê thời gian phục vụ"""
        # Tính toán thống kê thời gian phục vụ theo nhóm
        result = {
            'total_tokens': len(tokens),
            'service_times': [],
        }
        
        # Xử lý dữ liệu thời gian phục vụ
        # (Cần thêm logic cho thống kê thời gian phục vụ)
        
        return result