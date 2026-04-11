from django.db import migrations

def populate_labour_costs(apps, schema_editor):
    SalesResult = apps.get_model('sales', 'SalesResult')
    DirectSalePayment = apps.get_model('sales', 'DirectSalePayment')
    LabourCostConfig = apps.get_model('pricing', 'LabourCostConfig')
    
    def get_labour_config(date):
        config = LabourCostConfig.objects.filter(
            effective_from__lte=date
        ).order_by('-effective_from').first()
        if not config:
            config = LabourCostConfig.objects.order_by('effective_from').first()
        return config

    for sr in SalesResult.objects.all():
        config = get_labour_config(sr.date)
        if config:
            u_cost = float(config.labour_cost_per_sack)
            sr.labour_unit_cost = u_cost
            qty_eq = float(sr.qty_sold) + (float(sr.qty_pieces_sold) / 10.0)
            sr.total_labour_cost = u_cost * qty_eq
            sr.save()

    for dsp in DirectSalePayment.objects.all():
        config = get_labour_config(dsp.date)
        if config:
            u_cost = float(config.labour_cost_per_sack)
            dsp.labour_unit_cost = u_cost
            qty_eq = float(dsp.qty_sold)
            if dsp.product_size == '1kg':
                qty_eq = float(dsp.qty_sold) / 10.0
            dsp.total_labour_cost = u_cost * qty_eq
            dsp.save()

class Migration(migrations.Migration):
    dependencies = [
        ('sales', '0020_directsalepayment_labour_unit_cost_and_more'),
        ('pricing', '0014_remove_labourcostconfig_general_labour_cost_per_sack_and_more'),
    ]
    operations = [
        migrations.RunPython(populate_labour_costs),
    ]
