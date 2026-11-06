"""Preserve previous full-confirmation semantics; not a real-data migration plan."""
from django.db import migrations

def forward(apps, schema_editor):
    H=apps.get_model('commerce','MoneyHandover')
    R=apps.get_model('commerce','MoneyHandoverReceipt')
    for h in H.objects.using(schema_editor.connection.alias).filter(status='confirmed').iterator():
        receipt=R.objects.using(schema_editor.connection.alias).create(handover_id=h.pk,amount=h.amount,actor_id=h.decided_by_id,note='Previously confirmed full amount',source='legacy_full')
        if h.decided_at:
            R.objects.using(schema_editor.connection.alias).filter(pk=receipt.pk).update(created_at=h.decided_at)

class Migration(migrations.Migration):
    dependencies=[('commerce','0004_moneyhandoverreceipt')]
    operations=[migrations.RunPython(forward,migrations.RunPython.noop)]
