# -*- coding: utf-8 -*-
"""
    test_party

    :copyright: (c) 2013 by Openlabs Technologies & Consulting (P) Limited
    :license: GPLv3, see LICENSE for more details.
"""
import unittest

import trytond.tests.test_tryton
from trytond.transaction import Transaction
from trytond.exceptions import UserError
from trytond.tests.test_tryton import DB_NAME, USER, CONTEXT

from test_prestashop import get_objectified_xml, BaseTestCase


class TestProduct(BaseTestCase):
    """Test Product > Template/variant integration
    """

    def test_0010_product_template_import(self):
        """Test Product Template import
        """
        with Transaction().start(DB_NAME, USER, context=CONTEXT) as txn:
            # Call method to setup defaults
            self.setup_defaults()

            with Transaction().set_context(
                    prestashop_site=self.site.id, ps_test=True
                ):
                client = self.site.get_prestashop_client()

                self.assertEqual(len(self.ProductTemplate.search([])), 0)
                self.assertEqual(len(self.Product.search([])), 0)

                product_data = get_objectified_xml('products', 1)
                template = self.Product.find_or_create_using_ps_data(
                    product_data
                )
                # This should create a template and two variants where one
                # is created by template and other by this combination
                self.assertEqual(len(self.ProductTemplate.search([])), 1)
                self.assertEqual(len(self.Product.search([])), 1)

                # Try creating the same product again, it should NOT create a
                # new one and blow with user error due to sql constraint
                self.assertRaises(
                    UserError,
                    self.Product.create_using_ps_data, product_data
                )
                self.assertEqual(len(self.Product.search([])), 1)

                # Get template using prestashop data
                self.assertEqual(
                    template.id,
                    self.ProductTemplate.get_template_using_ps_data(
                        product_data
                    ).id
                )

                # Get template using prestashop ID
                self.assertEqual(
                    template.id,
                    self.ProductTemplate.get_template_using_ps_id(1).id
                )

    def test_0020_product_import(self):
        """Test Product import
        """
        with Transaction().start(DB_NAME, USER, context=CONTEXT) as txn:
            # Call method to setup defaults
            self.setup_defaults()

            with Transaction().set_context(
                    prestashop_site=self.site.id, ps_test=True
                ):
                client = self.site.get_prestashop_client()

                self.assertEqual(len(self.ProductTemplate.search([])), 0)
                self.assertEqual(len(self.Product.search([])), 0)

                product = self.Product.find_or_create_using_ps_data(
                    get_objectified_xml('combinations', 1)
                )
                # This should create a template and two variants where one
                # is created by template and other by this combination
                self.assertEqual(len(self.ProductTemplate.search([])), 1)
                self.assertEqual(len(self.Product.search([])), 2)

                # Try importing the same product again, it should NOT create a
                # new one.
                self.Product.find_or_create_using_ps_data(
                    get_objectified_xml('combinations', 1)
                )
                self.assertEqual(len(self.Product.search([])), 2)

                # Test getting product using prestashop data
                self.assertEqual(
                    product.id,
                    self.Product.get_product_using_ps_data(
                        product_data
                    ).id
                )

                # Test getting product using prestashop ID
                self.assertEqual(
                    product.id,
                    self.Product.get_product_using_ps_id(1).id
                )


def suite():
    "Prestashop Product test suite"
    suite = trytond.tests.test_tryton.suite()
    suite.addTests(
        unittest.TestLoader().loadTestsFromTestCase(TestProduct)
    )
    return suite


if __name__ == '__main__':
    unittest.TextTestRunner(verbosity=2).run(suite())
