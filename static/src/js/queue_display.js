odoo.define('hospital_queue_management.queue_display', function (require) {
    "use strict";

    var AbstractAction = require('web.AbstractAction');
    var core = require('web.core');
    var QWeb = core.qweb;
    var session = require('web.session');
    var ajax = require('web.ajax');
    var _t = core._t;
    var bus = require('bus.BusService');

    var QueueDisplay = AbstractAction.extend({
        template: 'QueueDisplay',
        events: {},

        init: function (parent, action) {
            this._super.apply(this, arguments);
            this.displayId = action.context.display_id || false;
            this.displayData = {};
            this.refreshInterval = 10000; // Default 10 seconds
        },

        willStart: function () {
            var self = this;
            return this._super.apply(this, arguments).then(function () {
                return self._loadDisplayData();
            });
        },

        start: function () {
            var self = this;
            return this._super.apply(this, arguments).then(function () {
                self._startAutoRefresh();
                bus.bus.add_channel('queue_display');
                bus.bus.on('notification', self, self._onNotification);
            });
        },

        _loadDisplayData: function () {
            var self = this;
            return this._rpc({
                route: '/queue/display/data',
                params: {
                    display_id: this.displayId
                },
            }).then(function (result) {
                self.displayData = result;
                self.refreshInterval = result.refresh_interval * 1000;
            });
        },

        _startAutoRefresh: function () {
            var self = this;
            this.refreshTimer = setInterval(function () {
                self._loadDisplayData().then(function () {
                    self._renderDisplay();
                });
            }, this.refreshInterval);
        },

        _renderDisplay: function () {
            this.$el.html(QWeb.render('QueueDisplayContent', {
                displayData: this.displayData
            }));
        },

        _onNotification: function (notifications) {
            var self = this;
            _.each(notifications, function (notification) {
                if (notification[0] === 'queue_display' && notification[1].event === 'queue_updated') {
                    self._loadDisplayData().then(function () {
                        self._renderDisplay();
                    });
                }
            });
        },

        destroy: function () {
            if (this.refreshTimer) {
                clearInterval(this.refreshTimer);
            }
            this._super.apply(this, arguments);
        },
    });

    core.action_registry.add('queue_display_client', QueueDisplay);

    return QueueDisplay;

});