# -*- coding: utf-8 -*-
"""
    sale

"""
from datetime import datetime
from decimal import Decimal

import pytz

from trytond.pool import PoolMeta, Pool
from trytond.transaction import Transaction


__all__ = ['Sale', 'SaleLine']
__metaclass__ = PoolMeta


class Sale:
    "Sale"
    __name__ = 'sale.sale'

    @classmethod
    def __setup__(cls):
        "Setup"
        super(Sale, cls).__setup__()
        cls._error_messages.update({
            'prestashop_client_not_found':
                'Prestashop client not found in context'
        })

    @classmethod
    def find_or_create_using_ps_data(cls, order_record):
        """Look for the sale in tryton corresponding to the order_record.
        If found, return the same else create a new one and return that.

        :param product_record: Objectified XML record sent by pystashop
        :returns: Active record of created sale
        """
        sale = cls.get_order_using_ps_data(order_record)

        if not sale:
            sale = cls.create_using_ps_data(order_record)

        return sale

    @classmethod
    def create_using_ps_data(cls, order_record):
        """Create an order from the order record sent by prestashop client

        :param order_record: Objectified XML record sent by pystashop
        :returns: Active record of created sale
        """
        Party = Pool().get('party.party')
        Address = Pool().get('party.address')
        Line = Pool().get('sale.line')
        SaleChannel = Pool().get('sale.channel')
        Currency = Pool().get('currency.currency')
        ChannelException = Pool().get('channel.exception')

        channel = SaleChannel(Transaction().context['current_channel'])

        channel.validate_prestashop_channel()
        client = channel.get_prestashop_client()

        if not client:
            cls.raise_user_error('prestashop_site_not_found')

        party = Party.find_or_create_using_ps_data(
            client.customers.get(order_record.id_customer.pyval)
        )

        # Get the sale date and convert the time to UTC from the application
        # timezone set on channel
        sale_time = datetime.strptime(
            order_record.date_add.pyval, '%Y-%m-%d %H:%M:%S'
        )
        channel_tz = pytz.timezone(channel.prestashop_timezone)
        sale_time_utc = pytz.utc.normalize(channel_tz.localize(sale_time))

        inv_address = Address.find_or_create_for_party_using_ps_data(
            party,
            client.addresses.get(order_record.id_address_invoice.pyval),
        )
        ship_address = Address.find_or_create_for_party_using_ps_data(
            party,
            client.addresses.get(order_record.id_address_delivery.pyval),
        )
        sale_data = {
            'reference': str(order_record.id.pyval),
            'channel_identifier': str(order_record.id.pyval),
            'description': order_record.reference.pyval,
            'sale_date': sale_time_utc.date(),
            'party': party.id,
            'invoice_address': inv_address.id,
            'shipment_address': ship_address.id,
            'currency': Currency.get_using_ps_id(
                order_record.id_currency.pyval
            ).id,
        }

        tryton_action = channel.get_tryton_action(
            unicode(order_record.current_state.pyval)  # current state is int
        )

        sale_data['invoice_method'] = tryton_action['invoice_method']
        sale_data['shipment_method'] = tryton_action['shipment_method']
        sale_data['channel'] = channel.id

        lines_data = []
        for order_line in order_record.associations.order_rows.iterchildren():
            lines_data.append(
                Line.get_line_data_using_ps_data(order_line)
            )

        if Decimal(str(order_record.total_shipping)):
            lines_data.append(
                Line.get_shipping_line_data_using_ps_data(order_record)
            )
        if Decimal(str(order_record.total_discounts)):
            lines_data.append(
                Line.get_discount_line_data_using_ps_data(order_record)
            )

        sale_data['lines'] = [('create', lines_data)]

        sale, = cls.create([sale_data])

        # Create channel exception if order total does not match
        if sale.total_amount != Decimal(
            str(order_record.total_paid_tax_excl)
        ):
            ChannelException.create([{
                'origin': '%s,%s' % (sale.__name__, sale.id),
                'log': 'Order total does not match. Expected %s, found %s' % (
                    sale.total_amount, Decimal(
                        str(order_record.total_paid_tax_excl))
                ),
                'channel': sale.channel.id,
            }])

            return sale

        sale.process_to_channel_state(
            unicode(order_record.current_state.pyval)  # Current state is int
        )
        return sale

    @classmethod
    def get_order_using_ps_data(cls, order_record):
        """Find an existing order in Tryton which matches the details
        of this order_record. By default it just matches the channel_identifier

        :param order_record: Objectified XML record sent by prestashop
        :returns: Active record if a sale is found else None
        """
        sales = cls.search([
            ('channel_identifier', '=', unicode(order_record.id.pyval)),
            ('channel', '=', Transaction().context.get('current_channel'))
        ])

        return sales and sales[0] or None

    def export_order_status_to_prestashop(self):
        """Update the status of this order in prestashop based on the order
        state in Tryton.

        """
        ChannelOrderState = Pool().get('sale.channel.order_state')

        client = self.channel.get_prestashop_client()

        new_prestashop_state = None

        if self.state == 'cancel':
            order_state, = ChannelOrderState.search([
                ('channel', '=', self.id),
                ('name', '=', 'Canceled'),
            ])
            new_prestashop_state = order_state.code
        elif self.state == 'done':
            # TODO: update shipping and invoice
            order_state, = ChannelOrderState.search([
                ('channel', '=', self.id),
                # XXX: Though final state in prestashop is delivered, but
                # till we don't have provision to get delivery status, set
                # it to shipped.
                ('name', '=', 'Shipped'),
            ])
            new_prestashop_state = order_state.code

        if not new_prestashop_state:
            return

        order = client.orders.get(self.channel_identifier)
        order.current_state = new_prestashop_state
        result = client.orders.update(order.id, order)

        return result.order


class SaleLine:
    "Sale Line"
    __name__ = 'sale.line'

    @classmethod
    def get_line_data_using_ps_data(cls, order_row_record):
        """Create the sale line from the order_row_record

        :param order_row_record: Objectified XML record sent by pystashop
        :returns: Sale line dictionary of values
        """
        SaleChannel = Pool().get('sale.channel')

        channel = SaleChannel(Transaction().context['current_channel'])
        channel.validate_prestashop_channel()

        client = channel.get_prestashop_client()

        # Import product
        product = channel.get_product(order_row_record)

        order_details = client.order_details.get(order_row_record.id.pyval)

        # FIXME: The number of digits handled in unit price should actually
        # from sale currency but the sale is not created yet.
        # We dont have order_data from prestashop either in this method.
        # How to do it? Use global variable or a class variable?
        return {
            'quantity': order_details.product_quantity.pyval,
            'product': product.id,
            'unit': channel.default_uom.id,
            'unit_price': Decimal(str(
                order_details.unit_price_tax_excl
            )).quantize(Decimal(10) ** - channel.company.currency.digits),
            'description': order_details.product_name.pyval,
        }

    @classmethod
    def get_taxes_data_using_ps_data(cls, order_record):
        """Create taxes using details order_record

        :param order_row_record: Objectified XML record sent by pystashop
        :returns: Sale line dictionary of values
        """
        # TODO: Handle taxes and create taxes on sale lines
        pass

    @classmethod
    def get_shipping_line_data_using_ps_data(cls, order_record):
        """Create shipping line using details order_record

        :param order_row_record: Objectified XML record sent by pystashop
        :returns: Sale line dictionary of values
        """
        SaleChannel = Pool().get('sale.channel')

        channel = SaleChannel(Transaction().context['current_channel'])
        return {
            'quantity': 1,
            'product': channel.prestashop_shipping_product.id,
            'unit_price': Decimal(str(
                order_record.total_shipping_tax_excl
            )).quantize(Decimal(10) ** - channel.company.currency.digits),
            'unit': channel.prestashop_shipping_product.default_uom.id,
            'description': 'Shipping Cost [Excl tax]',
        }

    @classmethod
    def get_discount_line_data_using_ps_data(cls, order_record):
        """Create discount line using details order_record

        :param order_row_record: Objectified XML record sent by pystashop
        :returns: Sale line dictionary of values
        """
        SaleChannel = Pool().get('sale.channel')

        channel = SaleChannel(Transaction().context['current_channel'])
        return {
            'quantity': 1,
            'unit_price': -Decimal(str(
                order_record.total_discounts_tax_excl
            )).quantize(Decimal(10) ** - channel.company.currency.digits),
            'description': 'Discount',
        }
