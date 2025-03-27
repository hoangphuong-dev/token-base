odoo.define('hospital_queue_management.view_tree_with_token', function (require) {
    "use strict";

    var ListController = require('web.ListController');
    var ListView = require('web.ListView');
    var viewRegistry = require('web.view_registry');

    var ViewTreeWithTokenController = ListController.extend({
        /**
         * @override
         */
        renderButtons: function ($node) {
            this._super.apply(this, arguments);
            if (this.$buttons) {
                this.$buttons.on('click', '.o_list_button_generate_token', this._onGenerateToken.bind(this));
            }
        },

        /**
         * Handler khi nhấn nút tạo token
         * @private
         */
        _onGenerateToken: function () {
            var self = this;
            var selectedRecords = this.getSelectedIds();

            if (selectedRecords.length === 0) {
                this.do_warn(_t("Cảnh Báo"), _t("Vui lòng chọn ít nhất một bệnh nhân."));
                return;
            }

            this.do_action({
                name: _t("Tạo Token Hàng Loạt"),
                type: 'ir.actions.act_window',
                res_model: 'queue.generate.token.wizard',
                views: [[false, 'form']],
                target: 'new',
                context: {
                    'default_patient_ids': selectedRecords,
                },
            });
        },
    });

    var ViewTreeWithToken = ListView.extend({
        config: _.extend({}, ListView.prototype.config, {
            Controller: ViewTreeWithTokenController,
        }),
    });

    viewRegistry.add('view_tree_with_token', ViewTreeWithToken);

});