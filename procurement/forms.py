from decimal import Decimal
import uuid
from django.utils import timezone
from django import forms
from .models import MATERIAL_CHOICES, RawMaterialReceipt


class RawReceiptForm(forms.ModelForm):
    request_key = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['material_type'].choices = [('', 'Select material'), *MATERIAL_CHOICES]

    class Meta:
        model = RawMaterialReceipt
        fields = ('date', 'material_type', 'supplier', 'num_bags', 'approx_weight_kg', 'reference_no', 'notes')
        labels = {
            'date': 'Date received', 'material_type': 'Material', 'supplier': 'Supplier',
            'num_bags': 'Number of bags', 'approx_weight_kg': 'Total weight (kg)',
            'reference_no': 'Delivery reference', 'notes': 'Notes',
        }
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'num_bags': forms.NumberInput(attrs={'min': 1, 'inputmode': 'numeric'}),
            'approx_weight_kg': forms.NumberInput(attrs={'min': '0.01', 'step': '0.01', 'inputmode': 'decimal'}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

    def clean_date(self):
        value = self.cleaned_data['date']
        if value > timezone.localdate():
            raise forms.ValidationError('Date cannot be in the future.')
        return value

    def clean_num_bags(self):
        value = self.cleaned_data['num_bags']
        if value <= 0:
            raise forms.ValidationError('Enter at least one bag.')
        return value

    def clean_approx_weight_kg(self):
        value = self.cleaned_data['approx_weight_kg']
        if value is not None and value <= Decimal('0'):
            raise forms.ValidationError('Enter a weight greater than zero.')
        return value


class PurchaseCostForm(forms.Form):
    cost_per_bag = forms.DecimalField(min_value=Decimal('0.01'), max_digits=12, decimal_places=2, widget=forms.NumberInput(attrs={'class':'form-input','step':'0.01','min':'0.01'}))
    revision_note = forms.CharField(required=False, max_length=300, widget=forms.TextInput(attrs={'class':'form-input'}))
