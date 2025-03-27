odoo.define('hospital_queue_management.dashboard', function (require) {
    "use strict";

    var AbstractAction = require('web.AbstractAction');
    var core = require('web.core');
    var QWeb = core.qweb;
    var rpc = require('web.rpc');
    var session = require('web.session');

    var QueueDashboard = AbstractAction.extend({
        template: 'QueueDashboard',
        events: {
            'click .token-action-button': '_onTokenActionClick',
            'click .room-action-button': '_onRoomActionClick',
            'click .refresh-dashboard': '_refreshDashboard',
        },

        init: function (parent, action) {
            this._super.apply(this, arguments);
            this.dashboardData = {};
            this.refreshInterval = 30000; // 30 seconds
        },

        willStart: function () {
            var self = this;
            return this._super.apply(this, arguments).then(function () {
                return self._fetchDashboardData();
            });
        },

        start: function () {
            var self = this;
            return this._super.apply(this, arguments).then(function () {
                self._renderDashboard();
                self._startAutoRefresh();
            });
        },

        _fetchDashboardData: function () {
            var self = this;
            return this._rpc({
                route: '/queue/dashboard/data',
            }).then(function (result) {
                self.dashboardData = result;
            });
        },

        _renderDashboard: function () {
            this.$('.o_queue_dashboard_content').html(
                QWeb.render('QueueDashboardContent', {
                    dashboardData: this.dashboardData,
                })
            );
        },

        _startAutoRefresh: function () {
            var self = this;
            clearInterval(this.refreshTimer);
            this.refreshTimer = setInterval(function () {
                self._refreshDashboard();
            }, this.refreshInterval);
        },

        _refreshDashboard: function () {
            var self = this;
            this._fetchDashboardData().then(function () {
                self._renderDashboard();
            });
        },

        _onTokenActionClick: function (ev) {
            ev.preventDefault();
            var action = $(ev.currentTarget).data('action');
            var tokenId = $(ev.currentTarget).data('token-id');
            this._callTokenAction(action, tokenId);
        },

        _onRoomActionClick: function (ev) {
            ev.preventDefault();
            var action = $(ev.currentTarget).data('action');
            var roomId = $(ev.currentTarget).data('room-id');
            this._callRoomAction(action, roomId);
        },

        _callTokenAction: function (action, tokenId) {
            var self = this;
            this._rpc({
                model: 'queue.token',
                method: action,
                args: [[tokenId]],
            }).then(function () {
                self._refreshDashboard();
            });
        },

        _callRoomAction: function (action, roomId) {
            var self = this;
            this._rpc({
                model: 'queue.room',
                method: action,
                args: [[roomId]],
            }).then(function () {
                self._refreshDashboard();
            });
        },

        destroy: function () {
            if (this.refreshTimer) {
                clearInterval(this.refreshTimer);
            }
            this._super.apply(this, arguments);
        },
    });

    core.action_registry.add('queue_dashboard', QueueDashboard);

    return QueueDashboard;
});