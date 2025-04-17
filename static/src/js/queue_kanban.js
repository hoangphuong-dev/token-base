odoo.define('hospital_queue_management.queue_kanban', function (require) {
    "use strict";

    var KanbanController = require('web.KanbanController');
    var KanbanView = require('web.KanbanView');
    var viewRegistry = require('web.view_registry');

    var QueueKanbanController = KanbanController.extend({
        buttons_template: 'QueueKanbanView.buttons',
        events: _.extend({}, KanbanController.prototype.events, {
            'click .o_queue_refresh': '_onRefreshClick',
            'click .o_queue_balance': '_onBalanceClick',
        }),

        /**
         * @override
         */
        init: function (parent, model, renderer, params) {
            this._super.apply(this, arguments);
            this.hasButtons = true;
        },

        _onRefreshClick: function (ev) {
            ev.preventDefault();
            this.reload();
        },

        _onBalanceClick: function (ev) {
            ev.preventDefault();
            var self = this;
            this._rpc({
                model: 'queue.token',
                method: '_run_load_balancing',
                args: [],
            }).then(function () {
                self.reload();
            });
        },
    });

    var QueueKanbanView = KanbanView.extend({
        config: _.extend({}, KanbanView.prototype.config, {
            Controller: QueueKanbanController,
        }),
    });

    viewRegistry.add('queue_token_kanban', QueueKanbanView);

    return {
        QueueKanbanController: QueueKanbanController,
        QueueKanbanView: QueueKanbanView,
    };

});