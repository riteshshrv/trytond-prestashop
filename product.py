# -*- coding: utf-8 -*-
"""
    product

"""
from itertools import groupby
from decimal import Decimal, ROUND_HALF_EVEN

from trytond.model import fields
from trytond.pool import PoolMeta, Pool
from trytond.pyson import Eval
from trytond.transaction import Transaction


__all__ = [
    'Product', 'ProductSaleChannelListing'
]
__metaclass__ = PoolMeta


def round_price(price):
    # XXX: Rounding prices to 4 decimal places.
    # In 3.6 rounding digites can be configured in tryton config
    return Decimal(price).quantize(
        Decimal('0.0001'), rounding=ROUND_HALF_EVEN
    )


class Product:
    "Product Variant"
    __name__ = 'product.product'

    @classmethod
    def create_from(cls, channel, product_data):
        """
        Create the product for the channel
        """
        if channel.source != 'prestashop':
            return super(Product, cls).create_from(channel, product_data)

        products = cls.search([
            ('code', '=', unicode(product_data.reference.pyval)),
        ])

        if products:
            return products[0]

        if product_data.tag == 'combination':
            product = cls.get_ps_combination_product(
                channel, product_data
            )
        elif product_data.tag == 'product':
            product = cls.get_ps_main_product(
                channel, product_data
            )

        return product

    @classmethod
    def get_ps_combination_product(cls, channel, combination_record):
        """
        Return prestashop combination product
        """
        client = channel.get_prestashop_client()

        main_product = cls.get_ps_main_product(
            channel, client.products.get(combination_record.id_product.pyval)
        )
        product, = cls.create([{
            'template': main_product.template.id,
            'code': unicode(combination_record.reference.pyval),
            'list_price': round_price(str(combination_record.price)),
            'cost_price': round_price(str(combination_record.wholesale_price)),
        }])
        return product

    @classmethod
    def extract_product_values_from_ps_data(
        cls, channel, name, product_data
    ):
        """
        Extract product values from the prestashop data, used for
        creation of product. This method can be overwritten by
        custom modules to store extra info to a product
        :param: product_data
        :returns: Dictionary of values
        """
        return {
            'name': name,
            'default_uom': channel.default_uom.id,
            'salable': True,
            'sale_uom': channel.default_uom.id,
        }

    @classmethod
    def get_ps_main_product(cls, channel, product_data):
        """
        Return prestashop main product
        """
        Template = Pool().get('product.template')
        Listing = Pool().get('product.product.channel_listing')
        SiteLang = Pool().get('prestashop.site.lang')

        # The name of a product can be in multiple languages
        # If the name is in more than one language, create the record with
        # name in first language (if a corresponding one exists on tryton) and
        # updates the rest of the names in different languages by switching the
        # language in context
        # Same applies to description as well
        name_in_langs = product_data.name.getchildren()
        desc_in_langs = product_data.description.getchildren()

        name_in_first_lang = name_in_langs.pop(0)
        desc_in_first_lang = desc_in_langs[0]
        site_lang = SiteLang.search_using_ps_id(
            int(name_in_first_lang.get('id'))
        )
        variant_data = {
            'code': unicode(product_data.reference.pyval),
            'list_price': round_price(str(product_data.price)),
            'cost_price': round_price(str(product_data.wholesale_price)),
        }
        # Product name and description can be in different first languages
        # So create the variant with description only if the first language is
        # same on both
        if name_in_first_lang.get('id') == desc_in_first_lang.get('id'):
            desc_in_first_lang = desc_in_langs.pop(0)
            variant_data['description'] = desc_in_first_lang.pyval

        # For a product in prestashop, create a template and a product in
        # tryton.
        with Transaction().set_context(language=site_lang.language.code):
            template_values = cls.extract_product_values_from_ps_data(
                channel, name_in_first_lang.pyval, product_data
            )
            template_values.update({
                'products': [('create', [variant_data])],
            })

            template, = Template.create([template_values])
            product, = template.products

        # If there is only lang for name, control wont go to this loop
        for name_in_lang in name_in_langs:
            # Write the name in other languages
            site_lang = SiteLang.search_using_ps_id(
                int(name_in_lang.get('id'))
            )
            if not site_lang:
                continue
            with Transaction().set_context(language=site_lang.language.code):
                Template.write([template], {
                    'name': name_in_lang.pyval,
                })

        # If there is only lang for description which has already been used,
        # control wont go to this loop
        for desc_in_lang in desc_in_langs:
            # Write the description in other languages
            site_lang = SiteLang.search_using_ps_id(
                int(desc_in_lang.get('id'))
            )
            if not site_lang:
                continue
            with Transaction().set_context(language=site_lang.language.code):
                cls.write(template.products, {
                    'description': desc_in_lang.pyval,
                })

        Listing.create_from(channel, product_data)

        return product


class ProductSaleChannelListing:
    "Product Sale Channel"
    __name__ = 'product.product.channel_listing'

    # Map main product
    prestashop_product_id = fields.Integer(
        'Prestashop ID', readonly=True, states={
            "invisible": Eval('channel_source') != 'prestashop'
        }, depends=['channel_source']
    )

    # Map product combination main product
    prestashop_combination_id = fields.Integer(
        'Prestashop Combination ID', readonly=True, states={
            "invisible": Eval('channel_source') != 'prestashop'
        }, depends=['channel_source']
    )

    @classmethod
    def create_from(cls, channel, product_data):
        """
        Create a listing for the product from channel and data
        """
        Product = Pool().get('product.product')

        if channel.source != 'prestashop':
            return super(ProductSaleChannelListing, cls).create_from(
                channel, product_data
            )

        try:
            product, = Product.search([
                ('code', '=', product_data.reference.pyval),
            ])
        except ValueError:
            cls.raise_user_error("No product found for mapping")

        identifier = unicode(product_data.reference.pyval)

        listings = cls.search([
            ('product_identifier', '=', identifier),
            ('channel', '=', channel)
        ])

        if listings:
            # XXX: Listing already exists
            return listings[0]

        listing = cls(
            channel=channel,
            product=product,
            product_identifier=identifier,
        )
        if product_data.tag == 'combination':
            listing.prestashop_combination_id = product_data.id.pyval
        elif product_data.tag == 'product':
            listing.prestashop_product_id = product_data.id.pyval
        listing.save()
        return listing

    def export_inventory(self):
        """
        Export inventory of this listing
        """
        if self.channel.source != 'prestashop':
            return super(ProductSaleChannelListing, self).export_inventory()

        return self.export_bulk_inventory([self])

    @classmethod
    def export_bulk_inventory(cls, listings):
        """
        Bulk export inventory to prestashop.
        Do not rely on the return value from this method.
        """
        if not listings:
            # Nothing to update
            return

        non_presta_listings = cls.search([
            ('id', 'in', map(int, listings)),
            ('channel.source', '!=', 'prestashop'),
        ])
        if non_presta_listings:
            super(ProductSaleChannelListing, cls).export_bulk_inventory(
                non_presta_listings
            )
        presta_listings = filter(
            lambda l: l not in non_presta_listings, listings
        )

        for channel, listings in groupby(presta_listings, lambda l: l.channel):
            client = channel.get_prestashop_client()
            # XXX: Prestashop manage stock in separate table for each
            # product. So actual stock record should be updated.
            # Fetch all stock records first then update all of them.

            # Separate Prestashop's main and combination product listing
            product_listings = {}
            combination_listings = {}
            for listing in listings:
                if listing.prestashop_combination_id:
                    combination_listings[listing.prestashop_combination_id] = \
                        listing
                else:
                    product_listings[listing.prestashop_product_id] = listing

            # TODO: fetch in batches
            product_stock_objects = client.stock_availables.get_list(
                display="full", filters={
                    # XXX: Stock should not be managed by Prestashop
                    'depends_on_stock': '0',
                    'id_product': '|'.join(
                        map(str, product_listings.keys())
                    )
                },
            ) if product_listings else []
            combination_stock_objects = client.stock_availables.get_list(
                display="full", filters={
                    # XXX: Stock should not be managed by Prestashop
                    'depends_on_stock': '0',
                    'id_product_attribute': '|'.join(
                        map(str, combination_listings.keys())
                    )
                },
            ) if combination_listings else []

            for stock_obj in product_stock_objects:
                # update product stock object with new quantity
                listing = product_listings[stock_obj.id_product]
                stock_obj.quantity = listing.quantity
                # TODO: Handle In/out of stock

            for stock_obj in combination_stock_objects:
                # update combination stock object with new quantity
                listing = combination_listings[
                    stock_obj.id_product_attribute
                ]
                stock_obj.quantity = listing.quantity
                # TODO: Handle In/out of stock

            # Push stock objects back to prestashop.
            # This could be done while updating stock object it self. But
            # prefer to be done separately.
            for stock_obj in (
                    combination_stock_objects + product_stock_objects):
                # XXX: Replace this with bulk update in future.
                client.stock_availables.update(stock_obj.id, stock_obj)
