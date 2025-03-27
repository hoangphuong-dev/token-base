# -*- coding: utf-8 -*-
from odoo import http, fields
from odoo.http import request
import json

class QueueController(http.Controller):
    @http.route('/queue/display/data', type='json', auth='user')
    def get_display_data(self, display_id=None):
        """Lấy dữ liệu cho màn hình hiển thị"""
        if not display_id:
            displays = request.env['queue.display'].search([], limit=1)
            if not displays:
                return {
                    'name': 'Hệ Thống Hàng Đợi',
                    'rooms': [],
                    'refresh_interval': 10,
                    'show_estimated_time': True
                }
            display = displays[0]
        else:
            display = request.env['queue.display'].browse(int(display_id))
            if not display.exists():
                return {'error': 'Không tìm thấy màn hình hiển thị'}
        
        return display.get_display_data()
    
    @http.route('/queue/token/info/<string:token_name>', type='http', auth='public')
    def get_token_info(self, token_name):
        """API công khai để kiểm tra thông tin token"""
        token = request.env['queue.token'].sudo().search([('name', '=', token_name)], limit=1)
        if not token:
            return json.dumps({'error': 'Token không tồn tại'})
        
        return json.dumps({
            'token': token.name,
            'patient': token.patient_id.name,
            'service': token.service_id.name,
            'room': token.room_id.name,
            'position': token.position,
            'wait_time': token.estimated_wait_time,
            'state': token.state,
            'priority': token.priority_id.name,
            'emergency': token.emergency,
        })
    
    @http.route('/queue/display/<int:display_id>', type='http', auth='public')
    def public_display(self, display_id):
        """Màn hình hiển thị công khai cho khu vực chờ"""
        display = request.env['queue.display'].sudo().browse(display_id)
        if not display.exists():
            return request.not_found()
        
        display_data = display.get_display_data()
        return request.render('hospital_queue_management.public_display_template', {
            'display': display,
            'display_data': display_data,
        })

    @http.route('/queue/dashboard/data', type='json', auth='user')
        
    def get_dashboard_data(self):
        """Lấy dữ liệu cho bảng điều khiển"""
        # Lấy tất cả phòng
        rooms = request.env['queue.room'].search([])
        room_data = []
        
        for room in rooms:
            # Token đang phục vụ
            current_token = request.env['queue.token'].search([
                ('room_id', '=', room.id),
                ('state', '=', 'in_progress')
            ], limit=1)
            
            # Tokens đang chờ
            waiting_tokens = request.env['queue.token'].search([
                ('room_id', '=', room.id),
                ('state', '=', 'waiting')
            ], order='position asc')
            
            # Thông tin phòng
            room_info = {
                'id': room.id,
                'name': room.name,
                'service': room.service_id.name,
                'state': room.state,
                'queue_length': room.queue_length,
                'estimated_wait_time': room.estimated_wait_time,
                'current_token': {
                    'id': current_token.id,
                    'name': current_token.name,
                    'patient': current_token.patient_id.name,
                    'priority': current_token.priority_id.name,
                    'emergency': current_token.emergency,
                    'start_time': current_token.start_time,
                } if current_token else False,
                'waiting_tokens': [{
                    'id': token.id,
                    'name': token.name,
                    'patient': token.patient_id.name,
                    'position': token.position,
                    'priority': token.priority_id.name,
                    'emergency': token.emergency,
                    'wait_time': round(token.estimated_wait_time),
                } for token in waiting_tokens]
            }
            
            room_data.append(room_info)
        
        # Thống kê tổng quan
        token_count = request.env['queue.token'].search_count([])
        waiting_count = request.env['queue.token'].search_count([('state', '=', 'waiting')])
        in_progress_count = request.env['queue.token'].search_count([('state', '=', 'in_progress')])
        completed_count = request.env['queue.token'].search_count([('state', '=', 'completed')])
        emergency_count = request.env['queue.token'].search_count([('emergency', '=', True), ('state', 'in', ['waiting', 'in_progress'])])
        
        # Dữ liệu dịch vụ
        services = request.env['queue.service'].search([])
        service_data = []
        
        for service in services:
            tokens = request.env['queue.token'].search([('service_id', '=', service.id)])
            waiting = request.env['queue.token'].search_count([
                ('service_id', '=', service.id),
                ('state', '=', 'waiting')
            ])
            
            service_info = {
                'id': service.id,
                'name': service.name,
                'total': len(tokens),
                'waiting': waiting,
                'avg_time': service.average_duration,
            }
            
            service_data.append(service_info)
        
        # Dữ liệu trả về
        return {
            'rooms': room_data,
            'services': service_data,
            'statistics': {
                'total': token_count,
                'waiting': waiting_count,
                'in_progress': in_progress_count,
                'completed': completed_count,
                'emergency': emergency_count,
            },
            'timestamp': fields.Datetime.now(),
        }