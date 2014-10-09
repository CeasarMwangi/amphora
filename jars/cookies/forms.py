from django import forms
from django.contrib.admin.widgets import FilteredSelectMultiple
from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import ValidationError
from django.utils.translation import ugettext as _

import autocomplete_light
import inspect

from . import models

class ChooseSchemaMethodForm(forms.Form):
    METHODS = (
        ('manual', 'Manual'),
        ('remote', 'Remote (RDF)'),
    )

    description = 'You can either create a schema manually or generate one' + \
                  ' from a RDF document.'
    schema_method = forms.ChoiceField(choices=METHODS)

class RemoteSchemaForm(forms.Form):
    schema_url = forms.URLField()
    domain = forms.models.ModelMultipleChoiceField(
                            queryset=models.Type.objects.all(),
                            required=False,
                            widget=FilteredSelectMultiple('types', False))

    class Media:
        css = {'all': ('/static/admin/css/widgets.css',),}
        js = ('/admin/jsi18n/',)

class ChooseResourceTypeForm(forms.Form):
    RTYPES = (
        ('localresource', 'Local'),
        ('remoteresource', 'Remote'),
    )
    
    # The description attribute is rendered in admin/generic_form.html
    description = 'Resources can be local (e.g. a text that you upload) or' + \
                  ' remote (e.g. a text in someone else\'s repository. You' + \
                  ' will be redirected to the appropriate form for adding a' +\
                  ' a resource based on your selection.'

    resource_type = forms.ChoiceField(choices=RTYPES)

class TargetField(forms.models.ModelChoiceField):
    """
    Supports the target field in the :class:`.RelationForm`\.
    """
    def to_python(self, value):
        """
        Supposed to convert a value entered into the field into an appropriate
        Python object for storage.
        
        In fact, here we just pass the value (str/unicode) on through, so that 
        we can evaluate it in :meth:`.RelationForm.clean`\.
        """
        
        return value

    def prepare_value(self, value):
        """
        Converts a Python object (``value``) back into something that we can
        display in the form.
        
        If value is an int, it is a primary key for :class:.`Entity`\. Otherwise
        (e.g. where there was a ValidationError) it is a value for ``name`` and 
        should be displayed directly.
        """
        
        if value is not None:
            if type(value) is int:
                entity = models.Entity.objects.get(pk=value)
                return entity.name
            else:
                return value
        return None


class ResourceForm(forms.ModelForm):
    class Meta:
        model = models.Resource

    def clean_name(self):
        """
        Ensure that an :class:`.Entity` with this name does not already exist.
        
        This is necessary because Django only checks against objects of the
        instantiated subclass, but we want to enforce the UNIQUE constraint
        across all Entities.
        """
        
        name = self.cleaned_data['name']
        
        # Look for Entities with the name that the user entered.
        matching = models.Entity.objects.filter(name=name)
        
        # count() minimizes database impact.
        if matching.count() > 0:
        
            # If instance.id is None, this is a new Resource; matching names
            #  should not be allowed under any circumstance. If the instance
            #  is the same as the only matching Entity, then the user is simply
            #  updating an existing Resource and a match is allowed.
            if self.instance.id is None or matching[0].id != self.instance.id:
            
                # Add an error to be displayed above the name input.
                self._errors['name'] = self.error_class(
                    ['Something with that name already exists.']
                    )
                del self.cleaned_data['name']
                return

        # If the name is indeed unique, pass it back.
        return name


class RelationForm(forms.ModelForm):
    """
    Supports the :class:`.RelationInline` by handling heterogeneous input and
    resolving them into Entities.
    
    TODO: Handle cases where the range of a Field includes non-Value types.
    """
    
    model = models.Relation
    
    def __init__(self, *args, **kwargs):
        super(RelationForm, self).__init__(*args, **kwargs)
        
        # We use a custom ModelChoiceField for target. This field will skip the
        #  usual conversions prior to passing the entered value along to
        #  the validation process. This lets us evaluate it directly in
        #  RelationForm.clean(), below.
        self.fields['target'] = TargetField(
                                    queryset=models.Entity.objects.all()    )
                                    
        # This autocomplete widget handles all Entity objects in the system. The
        #  desired outcome is that the user can use the same widget to select
        #  (and, in the case of Values, create) target Entities that are within
        #  the range of the selected predicate.
        self.fields['target'].widget = autocomplete_light.TextWidget(
                                        'EntityAutocomplete' )

        #  The admnin/base_site.html template includes a javascript
        #  (autocomplete_filter.js) that will listen for changes to the
        #  predicate field with class="autocomplete_filter" in a RelationInline,
        #  and pass the ID of the specified predicate (a Field) to the widget
        #  for "target" for inclusion in the suggestion GET request. The
        #  EntityAutocomplete (in autocomplete_light_registry) then uses a
        #  custom choice_for_request() method to filter Entities based on the
        #  range of the predicate Field.
        self.fields['predicate'].widget.widget.attrs.update(
            {
                'class': 'autocomplete_filter',
                'target': 'target',
            })
    
    def clean_target(self):
        return self.cleaned_data['target']

    def clean(self):
        """
        This custom :meth:`.clean` method adds extra data handling and
        validation for the ``target`` field.
        """
    
        # First get the usual cleanining out of the way.
        cleaned_data = super(RelationForm, self).clean()
        
        # Our main objective is to ensure that the selected target Entity is
        #  appropriate given the selected predicate Field. In other words,
        #  whether the Entity's "real" class is in the predicate Field's range.
        predicate = cleaned_data.get('predicate')

        # Get the user's input; this is untouched, since the TargetField's
        #  to_python() method just passed it along rather than recasting it. The
        #  reason we do it this way is that in some cases -- e.g. when the
        #  target Entity is a Value of some kind -- we will want to create a new
        #  Entity to store that input.
        target_data = cleaned_data.get('target')
        
        # Target data can't be blank.
        if len(target_data) == 0:
            self._errors['target'] = self.error_class(
                                        ['Cannot be blank.']
                                        )
            del cleaned_data['target']
            return cleaned_data     # We're completely done here.
        
        # First, attempt to get an Entity by name. At this point we don't know
        #  what kind of Entity it is (i.e. which subclass).
        try:
            target_obj = models.Entity.objects.get(name=target_data)
        
        # If that fails, try to cast the data based on any System fields in the
        #  predicate Field's range.
        except ObjectDoesNotExist:
            
            # Some Fields have an explicit range. If that's true for this
            #  predicate, we can use that to try to generate a Value for the
            #  target.
            if predicate.range.count() > 0:
            
                # Try to get a model for each System type in the predicate's
                #  range.
                cast = False
                for ftype in predicate.range.all():
                    if ftype.schema.name == 'System':
                    
                        # It is unlikely, but if there is no model corresponding
                        #  to the System type (ftype), then we should move on.
                        try:
                            candidate = models.__dict__[ftype.name]
                        except:
                            continue
                        
                        # If the model is retrieved successfully, we instantiate
                        #  it and assign the data to its name attribute.
                        try:
                            target_obj = candidate.objects.get_or_create(
                                                            name=target_data
                                                            )[0]

                            target_obj = target_obj.cast()
                            
                            # If the data is successfully cast as the selected
                            #  model, then we will stop here and proceed with
                            #  saving the Relation.
                            cast = True     # Evaluated below.
                            break
                            
                        # Otherwise, move on to the next type in the predicate's
                        #  range.
                        except (ValidationError, ValueError):
                            continue

            # If there is no explicit range for this predicate Field, just use
            #  a StringValue.
            else:
                try:
                    target_obj = models.Entity.objects.get(name=str(target_data)).cast()
                except ObjectDoesNotExist:
                    target_obj = models.StringValue()
                    target_obj.name = str(target_data)
                    target_obj.save()
                cast = True

            # If we can't find a way to represent the data that the user
            #  provided, we have no further recourse.
            if not cast:
                self._errors['target'] = self.error_class(
                                            ['Invalid value for this Field']
                                            )
                del cleaned_data['target']
                return cleaned_data     # We're completely done here.

        # If we made it this far, then we have succesfully created or retrieved
        #  an Entity that is a candidate for the Relation's target.
        
        # The cast() method will return the Entity retrieved above, but as an
        #  instance of its "real" class.
        target_obj = target_obj.cast()

        # The target must be in the Relation's Field's range. If the range is
        #  empty, then any Entity will do.
        if predicate.range.count() > 0:
            range = predicate.range.all()   # This is the database hit.
            
            # This should be an informative error message.
            range_msg = 'Value must be one of: {0}'.format(
                            ', '.join([str(r) for r in range])  )
            
            # The target Entity may nor may not have a Type associated with it.
            if hasattr(target_obj, 'entity_type'):
            
                # Here we check wheter the Entity's type is in range.
                if not target_obj.entity_type in range:
                    self._errors['target'] = self.error_class([range_msg])
                    del cleaned_data['target']
            
            # If the predicate has a range and the down-cast Entity has no type,
            #  there is no way for the Entity to be in range.
            else:
                self._errors['target'] = self.error_class([range_msg])
                del cleaned_data['target']

        # Success! Update cleaned_data to include the target Entity.
        cleaned_data['target'] = target_obj
        return cleaned_data
