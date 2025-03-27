odoo.define('hospital_queue_management.queue_token_form', function (require) {
    "use strict";

    var FormController = require('web.FormController');
    var FormView = require('web.FormView');
    var viewRegistry = require('web.view_registry');
    var core = require('web.core');
    var _t = core._t;

    var QueueTokenFormController = FormController.extend({
        /**
         * @override
         */
        renderButtons: function ($node) {
            this._super.apply(this, arguments);
            if (!this.$buttons) {
                return;
            }

            this.$buttons.on('click', '.o_queue_print_token', this._onPrintToken.bind(this));
            this.$buttons.on('click', '.o_queue_emergency_override', this._onEmergencyOverride.bind(this));
        },

        _onPrintToken: function () {
            var self = this;
            this.saveRecord().then(function () {
                self.do_action({
                    type: 'ir.actions.report',
                    report_name: 'hospital_queue_management.report_queue_token',
                    report_type: 'qweb-pdf',
                    context: { active_id: self.renderer.state.res_id },
                });
            });
        },

        _onEmergencyOverride: function () {
            var self = this;
            this.saveRecord().then(function () {
                self._rpc({
                    model: 'queue.token',
                    method: 'action_emergency_override',
                    args: [[self.renderer.state.res_id]],
                }).then(function () {
                    self.reload();
                    self.displayNotification({
                        title: _t('Thành Công'),
                        message: _t('Token đã được đánh dấu là khẩn cấp và được ưu tiên cao nhất.'),
                        type: 'success',
                    });
                });
            });
        },

        /**
         * @override
         */
        _updateButtons: function () {
            this._super.apply(this, arguments);
            if (this.$buttons) {
                var state = this.renderer.state;
                var emergency = state.data.emergency;
                var current_state = state.data.state;

                this.$buttons.find('.o_queue_emergency_override').toggleClass('d-none', emergency || current_state === 'completed' || current_state === 'cancelled');
            }
        },
    });

    var QueueTokenFormView = FormView.extend({
        config: _.extend({}, FormView.prototype.config, {
            Controller: QueueTokenFormController,
        }),
    });

    viewRegistry.add('queue_token_form', QueueTokenFormView);

});