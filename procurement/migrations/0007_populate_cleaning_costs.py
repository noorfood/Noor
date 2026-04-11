from django.db import migrations

def populate_cleaning_costs(apps, schema_editor):
    RawMaterialIssuance = apps.get_model('procurement', 'RawMaterialIssuance')
    CleaningCostConfig = apps.get_model('pricing', 'CleaningCostConfig')
    
    for ri in RawMaterialIssuance.objects.all():
        # Porting the logic from the save() method
        config = CleaningCostConfig.objects.filter(
            material_type=ri.material_type,
            effective_from__lte=ri.date
        ).order_by('-effective_from').first()
        
        if not config:
            # Fallback to earliest
            config = CleaningCostConfig.objects.filter(
                material_type=ri.material_type
            ).order_by('effective_from').first()
            
        if config:
            ri.cleaning_unit_cost = config.cleaning_cost_per_bag
            ri.total_cleaning_cost = float(config.cleaning_cost_per_bag) * float(ri.num_bags_issued)
            ri.save()

class Migration(migrations.Migration):
    dependencies = [
        ('procurement', '0006_rawmaterialissuance_cleaning_unit_cost_and_more'),
        ('pricing', '0014_remove_labourcostconfig_general_labour_cost_per_sack_and_more'),
    ]
    operations = [
        migrations.RunPython(populate_cleaning_costs),
    ]
