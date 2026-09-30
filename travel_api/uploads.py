"""
Upload path helpers and file cleanup shared by every model with a file field.
"""
import os
import uuid

from django.db.models.signals import post_delete, pre_save
from django.utils.deconstruct import deconstructible


@deconstructible
class UniqueUploadPath:
    """
    `upload_to` callable that stores files as <folder>/<uuid>.<ext>.

    Random names stop users from overwriting each other's files and avoid leaking
    the original filename (which may contain personal information). It is a
    deconstructible class rather than a closure so migrations can serialize it.
    """

    def __init__(self, folder):
        self.folder = folder

    def __call__(self, instance, filename):
        extension = os.path.splitext(filename)[1].lower()
        return f'{self.folder}/{uuid.uuid4().hex}{extension}'

    def __eq__(self, other):
        return isinstance(other, UniqueUploadPath) and self.folder == other.folder


def _delete_file(field_file):
    if field_file and field_file.name:
        field_file.storage.delete(field_file.name)


def register_file_cleanup(model, *field_names):
    """
    Remove files from storage when the row is deleted or the file is replaced,
    so the media directory doesn't fill up with orphans.
    """
    def on_delete(sender, instance, **kwargs):
        for name in field_names:
            _delete_file(getattr(instance, name))

    def on_replace(sender, instance, **kwargs):
        if not instance.pk:
            return
        old = sender.objects.filter(pk=instance.pk).only(*field_names).first()
        if old is None:
            return
        for name in field_names:
            old_file, new_file = getattr(old, name), getattr(instance, name)
            if old_file and old_file.name != getattr(new_file, 'name', None):
                _delete_file(old_file)

    uid = f'{model._meta.label}-file-cleanup'
    post_delete.connect(on_delete, sender=model, weak=False, dispatch_uid=f'{uid}-delete')
    pre_save.connect(on_replace, sender=model, weak=False, dispatch_uid=f'{uid}-replace')
