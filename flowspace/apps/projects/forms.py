from django import forms
from apps.common.uploads import validate_generic_upload
from .models import ProjectDocument


class ProjectDocumentForm(forms.ModelForm):

    class Meta:
        model = ProjectDocument
        fields = [
            "title",
            "file",
            "description"
        ]

    def clean_file(self):
        file = self.cleaned_data["file"]
        validate_generic_upload(file, max_size=20 * 1024 * 1024)
        return file