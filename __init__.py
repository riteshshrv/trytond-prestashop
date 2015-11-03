# -*- coding: utf-8 -*-
"""
    __init__

"""

from trytond.pool import Pool
from channel import (
    Channel, PrestashopExportOrdersWizardView, PrestashopConnectionWizardView,
    PrestashopExportOrdersWizard, PrestashopConnectionWizard
)
from country import (
    Country, Subdivision, CountryPrestashop, SubdivisionPrestashop
)
from currency import CurrencyPrestashop, Currency
from party import Party, Address, ContactMechanism
from product import Product, ProductSaleChannelListing
from sale import Sale, SaleLine
from lang import Language, SiteLanguage


def register():
    "Register classes with pool"
    Pool.register(
        Channel,
        PrestashopExportOrdersWizardView,
        PrestashopConnectionWizardView,
        Country,
        Subdivision,
        CountryPrestashop,
        SubdivisionPrestashop,
        Currency,
        CurrencyPrestashop,
        Language,
        SiteLanguage,
        Party,
        Address,
        ContactMechanism,
        Product,
        Sale,
        SaleLine,
        ProductSaleChannelListing,
        module='prestashop', type_='model')
    Pool.register(
        PrestashopExportOrdersWizard,
        PrestashopConnectionWizard,
        module='prestashop', type_='wizard')
