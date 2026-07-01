def certificate_file_upload_path(instance, filename):
    """
    Generate a unique file path for the uploaded certificate file.
    The path will be in the format: 'compliance_certificates/<property_id>/<filename>'
    """
    return f"compliance_certificates/{instance.property.id}/{filename}"


def tenant_avatar_upload_path(instance, filename):
    """
    Generate a unique file path for the uploaded tenant avatar.
    The path will be in the format: 'tenant_avatars/<tenant_id>/<filename>'
    """
    return f"tenant_avatars/{instance.id}/{filename}"
