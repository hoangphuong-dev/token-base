odoo.define('hospital_queue_management.queue_client_action', function (require) {
    "use strict";

    var core = require('web.core');
    var AbstractAction = require('web.AbstractAction');

    var QueueDisplayClient = AbstractAction.extend({
        template: 'QueueDisplayClient',

        init: function (parent, action) {
            this._super.apply(this, arguments);
            this.displayId = action.context && action.context.display_id;
        },

        start: function () {
            var self = this;
            return this._super.apply(this, arguments).then(function () {
                self._openDisplay();
            });
        },

        _openDisplay: function () {
            var self = this;
            this._rpc({
                model: 'queue.display',
                method: 'search',
                args: [[]],
                kwargs: {
                    limit: 1,
                },
            }).then(function (display_ids) {
                if (display_ids && display_ids.length) {
                    var displayId = self.displayId || display_ids[0];
                    var baseUrl = self.getSession().url('/');
                    var url = baseUrl + 'queue/display/' + displayId;
                    window.open(url, '_blank');
                    self.do_action({
                        type: 'ir.actions.act_window',
                        res_model: 'queue.display',
                        views: [[false, 'form']],
                        res_id: displayId,
                    });
                } else {
                    self.do_action({
                        type: 'ir.actions.act_window',
                        res_model: 'queue.display',
                        views: [[false, 'form']],
                        target: 'current',
                        context: {
                            create_display: true,
                        },
                    });s
                }
            });
        },
    });

    core.action_registry.add('queue_display_client', QueueDisplayClient);

    return QueueDisplayClient;

});