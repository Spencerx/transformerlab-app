import io
import posixpath
import zipfile
from typing import List


async def _add_file_to_zip(zip_file: zipfile.ZipFile, file_path: str, arcname: str, storage) -> None:
    async with await storage.open(file_path, "rb") as f:
        file_content = await f.read()
        zip_file.writestr(arcname, file_content)


async def _add_directory_to_zip(zip_file: zipfile.ZipFile, directory_path: str, root_prefix: str, storage) -> None:
    try:
        walk_entries = await storage.walk(directory_path)
    except Exception as e:
        print(f"Error walking directory during zipping: {directory_path}: {e}")
        return

    for root, _dirs, files in walk_entries:
        for file_name in files:
            file_path = storage.join(root, file_name)
            try:
                if not await storage.exists(file_path) or not await storage.isfile(file_path):
                    continue
                rel_from_dir = posixpath.relpath(file_path, directory_path)
                arcname = posixpath.join(root_prefix, rel_from_dir)
                await _add_file_to_zip(zip_file, file_path, arcname, storage)
            except Exception as e:
                print(f"Error adding nested file {file_path} to zip: {e}")
                continue


async def create_zip_from_storage(file_paths: List[str], storage) -> io.BytesIO:
    """
    Create a zip file in an in-memory buffer from a list of storage file paths.

    Args:
        file_paths: List of absolute file paths to include in the zip.
        storage: The storage backend to use for reading files.

    Returns:
        io.BytesIO: Buffer containing the zip file data.
    """
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for file_path in file_paths:
            try:
                # Determine a relative name for the file inside the zip
                # If it looks like a path, take the basename
                filename = file_path.split("/")[-1] if "/" in file_path else file_path

                # Check if file exists to avoid errors
                if not await storage.exists(file_path):
                    print(f"File not found during zipping: {file_path}")
                    continue

                if await storage.isdir(file_path):
                    await _add_directory_to_zip(zip_file, file_path, filename, storage)
                    continue

                if not await storage.isfile(file_path):
                    continue

                # Read file content from storage
                await _add_file_to_zip(zip_file, file_path, filename, storage)
            except Exception as e:
                print(f"Error adding file {file_path} to zip: {e}")
                # Continue with other files even if one fails
                continue

    zip_buffer.seek(0)
    return zip_buffer


async def create_zip_from_directory(directory_path: str, storage, root_prefix: str | None = None) -> io.BytesIO:
    """
    Create a zip file from a single directory path.
    """
    zip_buffer = io.BytesIO()
    prefix = root_prefix or (directory_path.split("/")[-1] if "/" in directory_path else directory_path)

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        await _add_directory_to_zip(zip_file, directory_path, prefix, storage)

    zip_buffer.seek(0)
    return zip_buffer
