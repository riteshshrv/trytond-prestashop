# -*- coding: utf-8 -*-
"""
    prestashop

"""
from datetime import datetime

import pytz
import requests
import pystashop
from mockstashop import MockstaShopWebservice
from trytond.model import ModelView, fields
from trytond.transaction import Transaction
from trytond.pool import Pool, PoolMeta
from trytond.wizard import Wizard, StateView, Button
from trytond.pyson import Eval

__metaclass__ = PoolMeta
__all__ = [
    'Channel', 'PrestashopExportOrdersWizardView',
    'PrestashopExportOrdersWizard',
    'PrestashopConnectionWizardView', 'PrestashopConnectionWizard',
]
TIMEZONES = [(None, '')] + [(x, x) for x in pytz.common_timezones]

PRESTASHOP_STATES = {
    'required': Eval('source') == 'prestashop',
    'invisible': ~(Eval('source') == 'prestashop')
}
INVISIBLE_IF_NOT_PRESTASHOP = {
    'invisible': ~(Eval('source') == 'prestashop')
}


class Channel:
    """
    Sale Channel model
    """
    __name__ = 'sale.channel'

    #: The URL of prestashop site
    prestashop_url = fields.Char(
        'Prestashop URL', states=PRESTASHOP_STATES, depends=['source']
    )

    #: The webservices key for access to site
    prestashop_key = fields.Char(
        'Prestashop Key', states=PRESTASHOP_STATES, depends=['source']
    )

    prestashop_shipping_product = fields.Many2One(
        'product.product', 'Shipping Product', states=PRESTASHOP_STATES,
        domain=[
            ('type', '=', 'service'),
            ('template.type', '=', 'service'),
            ('salable', '=', True),
        ], depends=['source']
    )

    #: The timezone set on prestashop site
    #: The orders imported will bear time in this timezone and that will need
    #: to be converted to UTC
    #: Also in order to determine what orders are to be imported, we need
    #: to convert UTC to this timezone to ensure correct time interval
    prestashop_timezone = fields.Selection(
        TIMEZONES, 'Timezone', translate=False, states=PRESTASHOP_STATES,
        depends=['source']
    )

    #: Allowed languages to be synced for the site
    prestashop_languages = fields.One2Many(
        'prestashop.site.lang', 'channel', 'Languages',
        states=INVISIBLE_IF_NOT_PRESTASHOP, depends=['source']
    )

    #: Set this to True to handle invoicing in tryton and get invoice info
    #: TODO: A provision to be implemented in future versions
    #: Also handle multiple payment methods where each will have different
    #: journal and account setups
    prestashop_handle_invoice = fields.Boolean(
        'Handle Invoicing ?', states=INVISIBLE_IF_NOT_PRESTASHOP,
        depends=['source']
    )

    @classmethod
    def get_source(cls):
        """
        Get the source
        """
        res = super(Channel, cls).get_source()
        res.append(('prestashop', 'Prestashop'))
        return res

    def validate_prestashop_channel(self):
        """
        Check if current channel belongs to prestashop
        """
        if self.source != 'prestashop':
            self.raise_user_error("invalid_prestashop_channel")

    @classmethod
    def __setup__(cls):
        super(Channel, cls).__setup__()
        cls._error_messages.update({
            'prestashop_settings_missing':
                'Prestashop webservice settings are incomplete.',
            'invalid_prestashop_channel':
                'Current channel does not belongs to prestashop',
            'multiple_channels':
                'Test connection can be done for only one channel at a time.',
            'wrong_url_n_key': 'Connection Failed! Please check URL and Key',
            'wrong_url': 'Connection Failed! The URL provided is wrong',
            'languages_not_imported':
                'Import the languages before importing order states',
            'order_states_not_imported':
                'Import the order states before importing/exporting orders'
        })
        cls._buttons.update({
            'test_prestashop_connection': {},
            'import_prestashop_languages': {},
            'export_prestashop_orders_button': {},
        })

    def get_prestashop_client(self):
        """
        Returns an authenticated instance of the Prestashop client

        :return: Prestashop client object
        """
        if not all([self.prestashop_url, self.prestashop_key]):
            self.raise_user_error('prestashop_settings_missing')

        if Transaction().context.get('ps_test'):
            return MockstaShopWebservice('Some URL', 'A Key')

        return pystashop.PrestaShopWebservice(
            self.prestashop_url, self.prestashop_key
        )

    @classmethod
    @ModelView.button
    def import_prestashop_languages(cls, channels):
        """Import Languages from remote and try to link them to tryton
        languages

        :param sites: List of sites for which the languages are to be imported
        :returns: List of languages created
        """
        SiteLanguage = Pool().get('prestashop.site.lang')

        if len(channels) != 1:
            cls.raise_user_error('multiple_channels')
        channel = channels[0]

        channel.validate_prestashop_channel()

        # Set this site in context
        with Transaction().set_context(current_channel=channel.id):

            client = channel.get_prestashop_client()
            languages = client.languages.get_list(display='full')

            new_records = []
            for lang in languages:
                # If the language already exists in `Languages`, skip and do
                # not create it again
                if SiteLanguage.search_using_ps_id(lang.id.pyval):
                    continue
                new_records.append(
                    SiteLanguage.create_using_ps_data(lang)
                )

        return new_records

    @classmethod
    @ModelView.button_action('prestashop.wizard_prestashop_connection')
    def test_prestashop_connection(cls, channels):
        """Test Prestashop connection and display appropriate message to user
        """
        if len(channels) != 1:
            cls.raise_user_error('multiple_channels')
        channel = channels[0]

        channel.validate_prestashop_channel()
        try:
            client = channel.get_prestashop_client()

            # Try getting the list of shops
            # If it fails with prestashop error, then raise error
            client.shops.get_list()
        except pystashop.PrestaShopWebserviceException:
            cls.raise_user_error('wrong_url_n_key')
        except (
            requests.exceptions.MissingSchema,
            requests.exceptions.ConnectionError
        ):
            cls.raise_user_error('wrong_url')

    def import_order_states(self):
        """
        Import order states for prestashop channel
        Downstream implementation for channel.import_order_states
        """
        SiteLanguage = Pool().get('prestashop.site.lang')

        if self.source != 'prestashop':
            return super(Channel, self).import_order_states()

        with Transaction().set_context({'current_channel': self.id}):

            # If channel languages don't exist, then raise an error
            if not self.prestashop_languages:
                self.raise_user_error('languages_not_imported')

            client = self.get_prestashop_client()
            order_states = client.order_states.get_list(display='full')

            for state in order_states:
                # The name of a state can be in multiple languages
                # If the name is in more than one language, create the record
                # with name in first language (if a corresponding one exists on
                # tryton) and updates the rest of the names in different
                # languages by switching the language in context
                name_in_langs = state.name.getchildren()
                name_in_first_lang = name_in_langs.pop(0)

                site_lang = SiteLanguage.search_using_ps_id(
                    int(name_in_first_lang.get('id'))
                )
                with Transaction().set_context(
                        language=site_lang.language.code):
                    self.create_order_state(
                        str(state.id.pyval), name_in_first_lang.pyval)

    def import_orders(self):
        """
        Downstream implementation of channel.import_orders

        Import orders for the current prestashop channel
        Import only those orders which are updated after the
        `last prestashop order import time` as set in the prestashop channel

        :returns: The list of active records of sales imported
        """
        if self.source != 'prestashop':
            return super(Channel, self).import_orders()

        Sale = Pool().get('sale.sale')
        self.validate_prestashop_channel()

        if not self.order_states:
            self.raise_user_error('order_states_not_imported')

        order_states_to_import = self.get_order_states_to_import()

        # Localize to the site timezone
        utc_time_now = datetime.utcnow()
        site_tz = pytz.timezone(self.prestashop_timezone)
        time_now = site_tz.normalize(pytz.utc.localize(utc_time_now))
        client = self.get_prestashop_client()

        with Transaction().set_context(current_channel=self.id):
            filters = {
                'current_state': '|'.join(map(
                    lambda s: s.code, order_states_to_import
                ))
            }
            if self.last_order_import_time:
                # In tryton all time stored is in UTC
                # Convert the last import time to timezone of the site
                last_order_import_time = site_tz.normalize(
                    pytz.utc.localize(self.last_order_import_time)
                )
                filters['date_upd'] = '{0},{1}'.format(
                    last_order_import_time.strftime(
                        '%Y-%m-%d %H:%M:%S'
                    ),
                    time_now.strftime('%Y-%m-%d %H:%M:%S')
                )
                orders_to_import = client.orders.get_list(
                    filters=filters, date=1, display='full'
                )
            else:
                orders_to_import = client.orders.get_list(
                    display='full', filters=filters
                )

            self.write([self], {
                'last_order_import_time': utc_time_now
            })
            sales_imported = []
            for order in orders_to_import:

                # TODO: Use import_order here
                sales_imported.append(Sale.find_or_create_using_ps_data(order))

        return sales_imported

    @classmethod
    def export_orders_to_prestashop_using_cron(cls):
        """
        Export order status to prestashop using cron
        """
        channels = cls.search([
            ('source', '=', 'prestashop')
        ])
        for channel in channels:
            channel.export_orders_to_prestashop()

    @classmethod
    @ModelView.button_action('prestashop.wizard_prestashop_export_orders')
    def export_prestashop_orders_button(cls, channels):
        """
        Dummy button to fire up the wizard for export of orders
        """
        pass

    def export_orders_to_prestashop(self):
        """
        Export order status to prestashop current site
        Export only those orders which are modified after the
        `last order export time` as set in the prestashop configuration.

        :returns: The list of active records of sales exported
        """
        Sale = Pool().get('sale.sale')
        Move = Pool().get('stock.move')

        if not self.order_states:
            self.raise_user_error('order_states_not_imported')

        time_now = datetime.utcnow()

        self.validate_prestashop_channel()

        with Transaction().set_context(current_channel=self.id):
            if self.last_order_export_time:
                # Sale might not get updated for state changes in the related
                # shipments.
                # So first get the moves for outgoing shipments which are \
                # executed after last import time.
                moves = Move.search([
                    (
                        'write_date', '>=',
                        self.last_order_export_time
                    ),
                    ('sale.channel', '=', self.id),
                    ('shipment', 'like', 'stock.shipment.out%')
                ])
                sales_to_export = Sale.search(['OR', [
                    (
                        'write_date', '>=',
                        self.last_order_export_time
                    ),
                    ('channel', '=', self.id),
                ], [
                    ('id', 'in', map(int, [m.sale for m in moves]))
                ]])
            else:
                sales_to_export = Sale.search([('channel', '=', self.id)])

            self.write([self], {
                'last_order_export_time': time_now
            })

            for sale in sales_to_export:
                sale.export_order_status_to_prestashop()

        return sales_to_export

    def import_product(self, order_row_record, product_data=None):
        """
        Import specific product for this prestashop channel
        Downstream implementation for channel.import_product
        """
        if self.source != 'prestashop':
            return super(Channel, self).import_product(
                order_row_record, product_data
            )

        Product = Pool().get('product.product')
        Listing = Pool().get('product.product.channel_listing')

        client = self.get_prestashop_client()

        if order_row_record.product_reference.pyval:
            sku = unicode(order_row_record.product_reference.pyval)
        else:
            # XXX: Sometime SKU may not come in order_line_data pull
            # product_data and get sku
            if order_row_record.product_attribute_id.pyval != 0:
                product_data = product_data or client.combinations.get(
                    order_row_record.product_attribute_id.pyval
                )
            else:
                product_data = product_data or client.products.get(
                    order_row_record.product_id.pyval
                )
            sku = product_data.reference.pyval

        products = Product.search([
            ('code', '=', sku),
        ])
        listings = Listing.search([
            ('product_identifier', '=', sku),
            ('channel', '=', self)
        ])

        if not products or not listings:
            # XXX: Fetch product data if it is not already being fetched
            if not product_data and \
                    order_row_record.product_attribute_id.pyval != 0:
                # Its a combination product
                product_data = client.combinations.get(
                    order_row_record.product_attribute_id.pyval
                )
            elif not product_data:
                # Its a main product
                product_data = client.products.get(
                    order_row_record.product_id.pyval
                )

            if not products:
                product = Product.create_from(self, product_data)
            else:
                product = products[0]

            if not listings:
                Listing.create_from(self, product_data)
        else:
            product = products[0]

        return product

    def get_default_tryton_action(self, code, name):
        """
        Return default tryton_actions for this channel
        """
        if self.source != 'prestashop':
            return super(Channel, self).get_default_tryton_action(code, name)

        # XXX: Prestashop do not have any standard code for state.
        # So cant think of any better way to map
        if name in ('Shipped', 'Delivered'):
            return {
                'action': 'import_as_past',
                'invoice_method': 'manual',
                'shipment_method': 'manual'
            }
        elif name in (
            'Payment accepted', 'Payment remotely accepted',
        ):
            return {
                'action': 'process_automatically',
                'invoice_method': 'order',
                'shipment_method': 'invoice'
            }
        elif name == 'Preparation in progress':
            return {
                'action': 'process_automatically',
                'invoice_method': 'order',
                'shipment_method': 'order'
            }
        else:
            return {
                'action': 'do_not_import',
                'invoice_method': 'manual',
                'shipment_method': 'manual',
            }


class PrestashopConnectionWizardView(ModelView):
    'Prestashop Connection Wizard View'
    __name__ = 'prestashop.connection.wizard.view'


class PrestashopConnectionWizard(Wizard):
    'Prestashop Connection Wizard'
    __name__ = 'prestashop.connection.wizard'

    start = StateView(
        'prestashop.connection.wizard.view',
        'prestashop.prestashop_connection_wizard_view_form',
        [
            Button('Ok', 'end', 'tryton-ok'),
        ]
    )

    def default_start(self, data):
        """Test the connection and show the user appropriate message

        :param data: Wizard data
        """
        return {}


class PrestashopExportOrdersWizardView(ModelView):
    'Prestashop Export Orders Wizard View'
    __name__ = 'prestashop.export_orders.wizard.view'

    orders_exported = fields.Integer('Orders Exported', readonly=True)


class PrestashopExportOrdersWizard(Wizard):
    'Prestashop Export Orders Wizard'
    __name__ = 'prestashop.export_orders.wizard'

    start = StateView(
        'prestashop.export_orders.wizard.view',
        'prestashop.prestashop_export_orders_wizard_view_form',
        [
            Button('Ok', 'end', 'tryton-ok'),
        ]
    )

    def default_start(self, fields):
        """
        Export the orders and display a confirmation message to the user

        :param fields: Wizard fields
        """
        SaleChannel = Pool().get('sale.channel')

        channel = SaleChannel(Transaction().context['active_id'])

        channel.validate_prestashop_channel()

        default = {
            'orders_exported': len(channel.export_orders_to_prestashop())
        }

        return default
