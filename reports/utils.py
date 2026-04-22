from django.db.models import Sum
from procurement.models import RawMaterialReceipt, RawMaterialIssuance
from cleaning.models import CleanRawReceipt
from finished_store.models import FinishedGoodsReceipt, FinishedGoodsIssuance, FinishedGoodsReturn
import datetime

def get_material_consumption_metrics(material_type, date_up_to=None):
    """
    Calculates the unit cost of clean material based on purchase history and yield.
    Yield = Raw Bags Issued / Clean Bags Returned.
    Clean Unit Cost = Avg Purchase Price * Yield Factor.
    """
    # 1. Average Purchase Price of Dirty Material (All time or up to date)
    receipts = RawMaterialReceipt.objects.filter(material_type=material_type, cost_status='approved')
    if date_up_to:
        receipts = receipts.filter(date__lte=date_up_to)
        
    totals = receipts.aggregate(
        bags=Sum('num_bags'),
        cost=Sum('total_cost')
    )
    total_bags = totals['bags'] or 0
    total_cost = totals['cost'] or 0
    
    avg_dirty_cost = float(total_cost) / float(total_bags) if total_bags > 0 else 0
    
    # 2. Yield Factor (Historical efficiency)
    # We use all-time yield for stability, or period yield if preferred.
    # Total bags that went into cleaning vs what came out.
    issuances = RawMaterialIssuance.objects.filter(material_type=material_type)
    if date_up_to:
        issuances = issuances.filter(date__lte=date_up_to)
    dirty_issued = issuances.aggregate(t=Sum('num_bags_issued'))['t'] or 0
    
    clean_receipts = CleanRawReceipt.objects.filter(material_type=material_type)
    if date_up_to:
        clean_receipts = clean_receipts.filter(date__lte=date_up_to)
    clean_returned = clean_receipts.aggregate(t=Sum('num_bags'))['t'] or 0
    
    # Yield Factor: 100 dirty -> 95 clean = 1.052 multiplier
    yield_factor = (float(dirty_issued) / float(clean_returned)) if clean_returned > 0 else 1.05
    
    clean_unit_cost = avg_dirty_cost * yield_factor
    
    return {
        'avg_dirty_cost': avg_dirty_cost,
        'yield_factor': yield_factor,
        'clean_unit_cost': clean_unit_cost,
        'total_raw_bags': total_bags
    }

def get_inventory_valuation(material_type):
    """
    Estimates the current cost-value of stock in all stages.
    """
    metrics = get_material_consumption_metrics(material_type)
    dirty_cost = metrics['avg_dirty_cost']
    clean_cost = metrics['clean_unit_cost']
    
    # Raw Store (Dirty)
    from procurement.models import RawMaterialReceipt, RawMaterialIssuance
    raw_in = RawMaterialReceipt.objects.filter(material_type=material_type).aggregate(t=Sum('num_bags'))['t'] or 0
    raw_out = RawMaterialIssuance.objects.filter(material_type=material_type).aggregate(t=Sum('num_bags_issued'))['t'] or 0
    raw_bal = max(0, raw_in - raw_out)
    raw_value = raw_bal * dirty_cost
    
    # Clean Store
    from clean_store.views import _get_clean_store_balance
    clean_bal = _get_clean_store_balance(material_type)
    clean_value = clean_bal * clean_cost
    
    # Finished Goods Store (10kg sacks)
    from finished_store.views import _fg_balance
    fg_bal = _fg_balance(material_type, '10kg')
    # Cost of a finished sack = (Clean Bag Cost) / 10 + Packaging Cost
    # Assuming standard 100kg clean bag -> 10 sacks of 10kg.
    from pricing.models import PackagingCostConfig
    p_config = PackagingCostConfig.get_active_config(datetime.date.today())
    p_cost = float(p_config.cost_per_sack + p_config.nylon_cost_per_piece) if p_config else 0
    
    fg_unit_cost = (clean_cost / 10.0) + p_cost
    fg_value = fg_bal * fg_unit_cost
    
    return {
        'raw_balance': raw_bal,
        'raw_value': raw_value,
        'clean_balance': clean_bal,
        'clean_value': clean_value,
        'fg_balance': fg_bal,
        'fg_value': fg_value,
        'total_value': raw_value + clean_value + fg_value
    }
