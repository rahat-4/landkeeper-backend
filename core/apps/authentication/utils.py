def profile_image_upload_path(instance, filename):
    return f"user/profile/{instance.id}/{filename}"
