import uuid
from decimal import Decimal
from django import forms
from django.utils import timezone
from accounts.models import User
from procurement.models import MATERIAL_CHOICES
from bag_stock.models import CleaningJob, SHIFT_CHOICES

class BaseForm(forms.Form):
    request_key=forms.UUIDField(widget=forms.HiddenInput,initial=uuid.uuid4)
    date=forms.DateField(label='Date',initial=timezone.localdate,widget=forms.DateInput(attrs={'type':'date'}))
    def clean_date(self):
        date=self.cleaned_data['date']
        if date>timezone.localdate(): raise forms.ValidationError('Date cannot be in the future.')
        return date

def bags(label,allow_zero=False):
    return forms.IntegerField(label=label,min_value=0 if allow_zero else 1,max_value=2147483647,widget=forms.NumberInput(attrs={'min':0 if allow_zero else 1,'step':1,'inputmode':'numeric'}))
def weight(label,allow_zero=False):
    return forms.DecimalField(label=label,required=False,min_value=Decimal("0") if allow_zero else Decimal("0.01"),max_digits=12,decimal_places=2,widget=forms.NumberInput(attrs={'step':'0.01','min':0 if allow_zero else '0.01','inputmode':'decimal'}))

class CleaningIssueForm(BaseForm):
    material=forms.ChoiceField(label='Material',choices=[('','Select material'),*MATERIAL_CHOICES])
    cleaner=forms.CharField(label='Cleaner',max_length=200)
    bags=bags('Bags sent')
    weight_kg=weight('Weight sent (kg)')

class CleaningReturnForm(BaseForm):
    job=forms.ModelChoiceField(label='Cleaning record',queryset=CleaningJob.objects.none(),empty_label='Select cleaning record')
    clean_bags=bags('Clean bags received',allow_zero=True)
    return_type=forms.ChoiceField(label='Return type',choices=[('','Select return type'),('partial','Partial return'),('final','Final return')])
    clean_weight_kg=weight('Clean weight received (kg)')
    loss_weight_kg=weight('Measured loss (kg)',allow_zero=True)
    def __init__(self,*a,**kw):
        super().__init__(*a,**kw)
        self.fields['job'].queryset=CleaningJob.objects.filter(status='in_progress')
        self.fields['job'].label_from_instance=lambda obj:f'#{obj.pk} · {obj.get_material_display()} · {obj.cleaner} · {obj.issued_bags} bags sent'
    def clean(self):
        data=super().clean()
        if data.get('job') and data.get('date') and data['date']<data['job'].date:self.add_error('date','Date cannot be before the material was sent.')
        return data

class ProductionIssueForm(BaseForm):
    material=forms.ChoiceField(label='Material',choices=[('','Select material'),*MATERIAL_CHOICES])
    bags=bags('Bags sent')
    weight_kg=weight('Weight sent (kg)')
    recipient=forms.ModelChoiceField(label='Production officer',queryset=User.objects.none(),empty_label='Select officer')
    def __init__(self,*a,**kw):
        super().__init__(*a,**kw)
        self.fields['recipient'].queryset=User.objects.filter(role='production_officer',status='active').order_by('full_name')
        self.fields['recipient'].label_from_instance=lambda obj:obj.full_name

class DecisionForm(forms.Form):
    decision=forms.ChoiceField(choices=[('accept','Accept'),('reject','Return')],widget=forms.HiddenInput)
    reason=forms.CharField(label='Reason',required=False,max_length=300)
    def clean(self):
        data=super().clean()
        if data.get('decision')=='reject' and not data.get('reason','').strip():self.add_error('reason','Enter a reason for returning the handover.')
        return data


class MillingForm(BaseForm):
    material=forms.ChoiceField(label='Material',choices=[('','Select material'),*MATERIAL_CHOICES])
    shift=forms.ChoiceField(label='Shift',choices=[('','Select shift'),*SHIFT_CHOICES])
    bags=bags('Clean bags milled')
    input_weight_kg=weight('Input weight (kg)')
    powder_kg=forms.DecimalField(label='Powder produced (kg)',min_value=Decimal('0.01'),max_digits=12,decimal_places=2,widget=forms.NumberInput(attrs={'min':'0.01','step':'0.01','inputmode':'decimal'}))
    powder_bags=forms.IntegerField(label='Powder bags produced',required=False,min_value=1,max_value=2147483647,widget=forms.NumberInput(attrs={'min':1,'step':1,'inputmode':'numeric'}))
    machine=forms.CharField(label='Machine',required=False,max_length=100)

class PackagingForm(BaseForm):
    material=forms.ChoiceField(label='Material',choices=[('','Select material'),*MATERIAL_CHOICES])
    shift=forms.ChoiceField(label='Shift',choices=[('','Select shift'),*SHIFT_CHOICES])
    powder_used_kg=weight('Powder used (kg)')
    powder_used_bags=forms.IntegerField(label='Powder bags used',required=False,min_value=1,max_value=2147483647,widget=forms.NumberInput(attrs={'min':1,'step':1,'inputmode':'numeric'}))
    packs=bags('Number of packs')
    pack_size_kg=forms.DecimalField(label='Pack size (kg)',min_value=Decimal('0.01'),max_digits=8,decimal_places=2,widget=forms.NumberInput(attrs={'min':'0.01','step':'0.01','inputmode':'decimal'}))


class FinishedIssueForm(BaseForm):
    material=forms.ChoiceField(label='Product',choices=[('','Select product'),*MATERIAL_CHOICES])
    pack_size_kg=forms.DecimalField(label='Pack size (kg)',min_value=Decimal('0.01'),max_digits=8,decimal_places=2,widget=forms.NumberInput(attrs={'min':'0.01','step':'0.01','inputmode':'decimal'}))
    packs=bags('Packs sent')
    recipient=forms.ModelChoiceField(label='Finished-goods store officer',queryset=User.objects.none(),empty_label='Select officer')
    def __init__(self,*a,**kw):
        super().__init__(*a,**kw)
        self.fields['recipient'].queryset=User.objects.filter(role='store_officer',store_type='finished',status='active').order_by('full_name')
        self.fields['recipient'].label_from_instance=lambda obj:obj.full_name

class FinishedReceiptForm(forms.Form):
    request_key=forms.UUIDField(widget=forms.HiddenInput,initial=uuid.uuid4)
    packs=bags('Packs received')
    receipt_type=forms.ChoiceField(label='Receipt type',choices=[('','Select receipt type'),('partial','Partial receipt'),('final','Final receipt')])
    reason=forms.CharField(label='Reason',required=False,max_length=300)

class FinishedReviewForm(forms.Form):
    reason=forms.CharField(label='Reason',max_length=300)

class FinishedReturnForm(forms.Form):
    request_key=forms.UUIDField(widget=forms.HiddenInput,initial=uuid.uuid4)
    packs=bags('Packs returned')

class FinishedResolveForm(forms.Form):
    note=forms.CharField(label='Resolution note',max_length=300)

class FinishedReviewNoteForm(forms.Form):
    request_key=forms.UUIDField(widget=forms.HiddenInput,initial=uuid.uuid4)
    note=forms.CharField(label='Review note',max_length=1000,widget=forms.Textarea(attrs={'rows':3}))

class FinishedStoreCountForm(forms.Form):
    request_key=forms.UUIDField(widget=forms.HiddenInput,initial=uuid.uuid4)
    material=forms.ChoiceField(label='Product',choices=[('','Select product'),*MATERIAL_CHOICES])
    pack_size_kg=forms.DecimalField(label='Pack size (kg)',min_value=Decimal('0.01'),max_digits=8,decimal_places=2,widget=forms.NumberInput(attrs={'min':'0.01','step':'0.01','inputmode':'decimal'}))
    counted_packs=bags('Packs counted',allow_zero=True)
    counted_at=forms.DateTimeField(label='Count date and time (Lagos time)',widget=forms.DateTimeInput(attrs={'type':'datetime-local'},format='%Y-%m-%dT%H:%M'))
    scope=forms.CharField(label='What was counted',max_length=300,widget=forms.TextInput(attrs={'placeholder':'e.g. Store shelves'}))
    note=forms.CharField(label='Notes',max_length=1000,required=False,widget=forms.Textarea(attrs={'rows':3}))
    def clean_counted_at(self):
        value=self.cleaned_data['counted_at']
        if value>timezone.now():raise forms.ValidationError('Count time cannot be in the future.')
        return value

class SalesGoodsSendForm(BaseForm):
    material=forms.ChoiceField(label='Product',choices=[('','Select product'),*MATERIAL_CHOICES])
    pack_size_kg=forms.DecimalField(label='Pack size (kg)',min_value=Decimal('0.01'),max_digits=8,decimal_places=2,widget=forms.NumberInput(attrs={'min':'0.01','step':'0.01','inputmode':'decimal'}))
    packs=bags('Packs sent')
    recipient=forms.ModelChoiceField(label='Sales manager',queryset=User.objects.none(),empty_label='Select sales manager')
    def __init__(self,*a,**kw):
        super().__init__(*a,**kw)
        self.fields['recipient'].queryset=User.objects.filter(role='sales_manager',status='active').order_by('full_name')
        self.fields['recipient'].label_from_instance=lambda obj:obj.full_name
