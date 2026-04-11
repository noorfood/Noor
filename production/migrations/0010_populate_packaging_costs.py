from django.db import migrations

def populate_packaging_costs(apps, schema_editor):
    PackagingBatch = apps.get_model('production', 'PackagingBatch')
    PackagingCostConfig = apps.get_model('pricing', 'PackagingCostConfig')
    
    for pb in PackagingBatch.objects.all():
        config = PackagingCostConfig.objects.filter(
            effective_from__lte=pb.date
        ).order_by('-effective_from').first()
        
        if not config:
            # Fallback to earliest
            config = PackagingCostConfig.objects.order_by('effective_from').first()
            
        if config:
            u_cost = float(config.cost_per_sack) + float(config.nylon_cost_per_piece)
            pb.packaging_unit_cost = u_cost
            pb.total_packaging_cost = u_cost * float(pb.qty_10kg)
            pb.save()

class Migration(migrations.Migration):
    dependencies = [
        ('production', '0009_packagingbatch_packaging_unit_cost_and_more'),
        ('pricing', '0014_remove_labourcostconfig_general_labour_cost_per_sack_and_more'),
    ]
    operations = [
        migrations.RunPython(populate_packaging_costs),
    ]
