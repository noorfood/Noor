import uuid
from decimal import Decimal
from django import forms
from django.utils import timezone
from procurement.models import MATERIAL_CHOICES
from bag_stock.services import VALID_MATERIALS

class SaleForm(forms.Form):
    request_key=forms.UUIDField(widget=forms.HiddenInput,initial=uuid.uuid4)
    date=forms.DateField(label='Date',initial=timezone.localdate,widget=forms.DateInput(attrs={'type':'date'}))
    material=forms.ChoiceField(label='Product',choices=[('','Select product'),*MATERIAL_CHOICES])
    pack_size_kg=forms.DecimalField(label='Pack size (kg)',max_digits=8,decimal_places=2,min_value=Decimal('0.01'),widget=forms.NumberInput(attrs={'min':'0.01','step':'0.01','inputmode':'decimal'}))
    packs=forms.IntegerField(label='Packs sold',min_value=1,max_value=2147483647,widget=forms.NumberInput(attrs={'min':1,'step':1,'inputmode':'numeric'}))
    unit_price=forms.DecimalField(label='Price per pack (₦)',max_digits=12,decimal_places=2,min_value=Decimal('0.01'),widget=forms.NumberInput(attrs={'min':'0.01','step':'0.01','inputmode':'decimal'}))
    buyer=forms.CharField(label='Buyer',max_length=200,required=False)
    notes=forms.CharField(label='Notes',max_length=1000,required=False,widget=forms.Textarea(attrs={'rows':3}))
    def clean_date(self):
        value=self.cleaned_data['date']
        if value>timezone.localdate():raise forms.ValidationError('Date cannot be in the future.')
        return value

class CustomerPaymentForm(forms.Form):
    request_key=forms.UUIDField(widget=forms.HiddenInput,initial=uuid.uuid4)
    date=forms.DateField(label='Date received',initial=timezone.localdate,widget=forms.DateInput(attrs={'type':'date'}))
    method=forms.ChoiceField(label='Payment method',choices=[('','Select method'),('cash','Cash'),('transfer','Transfer')])
    amount=forms.DecimalField(label='Amount (₦)',max_digits=14,decimal_places=2,min_value=Decimal('0.01'),widget=forms.NumberInput(attrs={'min':'0.01','step':'0.01','inputmode':'decimal'}))
    note=forms.CharField(label='Notes',max_length=500,required=False,widget=forms.Textarea(attrs={'rows':3}))
    def clean_date(self):
        value=self.cleaned_data['date']
        if value>timezone.localdate():raise forms.ValidationError('Date cannot be in the future.')
        return value

class MoneyHandoverForm(forms.Form):
    request_key=forms.UUIDField(widget=forms.HiddenInput,initial=uuid.uuid4)
    date=forms.DateField(label='Date sent',initial=timezone.localdate,widget=forms.DateInput(attrs={'type':'date'}))
    recipient=forms.ModelChoiceField(label='Recipient',queryset=None,empty_label='Select recipient')
    method=forms.ChoiceField(label='Payment method',choices=[('','Select method'),('cash','Cash'),('transfer','Transfer')])
    amount=forms.DecimalField(label='Amount (₦)',max_digits=14,decimal_places=2,min_value=Decimal('0.01'),widget=forms.NumberInput(attrs={'min':'0.01','step':'0.01','inputmode':'decimal'}))
    reference=forms.CharField(label='Reference',max_length=150,required=False)
    note=forms.CharField(label='Notes',max_length=500,required=False,widget=forms.Textarea(attrs={'rows':3}))
    def __init__(self,*args,actor,**kwargs):
        from accounts.models import User
        super().__init__(*args,**kwargs)
        role='manager' if actor.role=='sales_manager' else 'md'
        self.fields['recipient'].queryset=User.objects.filter(status='active',role=role).exclude(pk=actor.pk).order_by('full_name','pk')
    def clean_date(self):
        d=self.cleaned_data['date']
        if d>timezone.localdate():raise forms.ValidationError('Date cannot be in the future.')
        return d

class MoneyDecisionForm(forms.Form):
    decision=forms.ChoiceField(choices=[('confirmed','Confirm receipt'),('review','Request review')],widget=forms.HiddenInput)
    reason=forms.CharField(label='Reason',max_length=500,required=False,widget=forms.Textarea(attrs={'rows':3}))
    def clean(self):
        d=super().clean()
        if d.get('decision')=='review' and not d.get('reason','').strip():self.add_error('reason','Enter a reason for review.')
        return d

class MoneyReceiptForm(forms.Form):
    request_key=forms.UUIDField(widget=forms.HiddenInput,initial=uuid.uuid4)
    amount=forms.DecimalField(label='Amount received now (₦)',max_digits=14,decimal_places=2,min_value=Decimal('0.01'),widget=forms.NumberInput(attrs={'min':'0.01','step':'0.01','inputmode':'decimal'}))
    note=forms.CharField(label='Note',max_length=500,required=False,widget=forms.Textarea(attrs={'rows':3}))

class _PaymentChoice(forms.ModelChoiceField):
    def label_from_instance(self,obj):
        return f'Sale #{obj.sale_id} · {obj.date:%d %b %Y} · ₦{obj.amount} · {obj.get_method_display()}'

class ReportedAllocationForm(forms.Form):
    request_key=forms.UUIDField(widget=forms.HiddenInput,initial=uuid.uuid4)
    payment=_PaymentChoice(queryset=None,label='Reported customer payment',empty_label='Select payment')
    amount=forms.DecimalField(label='Amount linked (₦)',max_digits=14,decimal_places=2,min_value=Decimal('0.01'),widget=forms.NumberInput(attrs={'min':'0.01','step':'0.01','inputmode':'decimal'}))
    note=forms.CharField(label='Note',max_length=500,required=False,widget=forms.Textarea(attrs={'rows':3}))
    def __init__(self,*args,actor,**kwargs):
        super().__init__(*args,**kwargs)
        from .models import ReportedCustomerPayment
        self.fields['payment'].queryset=ReportedCustomerPayment.objects.filter(recorded_by=actor).select_related('sale').order_by('-created_at','-id')

class MoneyCorrectionRequestForm(forms.Form):
    request_key=forms.UUIDField(widget=forms.HiddenInput,initial=uuid.uuid4)
    reason=forms.CharField(label='Reason',max_length=500,widget=forms.Textarea(attrs={'rows':3}))

class MoneyCorrectionDecisionForm(forms.Form):
    decision=forms.ChoiceField(choices=[('approved','Approve'),('rejected','Reject')],widget=forms.HiddenInput)
    note=forms.CharField(label='Decision note',max_length=500,widget=forms.Textarea(attrs={'rows':3}))
