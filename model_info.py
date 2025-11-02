import os
import json
from typing import Dict, List, Optional
from config import get_config

class ModelInfoManager:
    """Manages model descriptions and images for the dashboard"""

    def __init__(self):
        self.config = get_config()
        self.models_dir = os.path.join(self.config.RESULTS_DIR, "models")
        self.model_info = {}
        self.load_model_info()

    def load_model_info(self):
        """Load model descriptions and image information"""
        if not os.path.exists(self.models_dir):
            return

        for model_name in os.listdir(self.models_dir):
            model_path = os.path.join(self.models_dir, model_name)
            if os.path.isdir(model_path):
                self.model_info[model_name] = {
                    'description': self.load_model_description(model_path),
                    'images': self.load_model_images(model_path),
                    'metadata': self.load_model_metadata(model_path)
                }

    def load_model_description(self, model_path: str) -> Optional[str]:
        """Load model description from metadata.json"""
        metadata_file = os.path.join(model_path, "metadata.json")
        if os.path.exists(metadata_file):
            try:
                with open(metadata_file, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
                    return metadata.get('description', None)
            except Exception as e:
                print(f"Error loading description for {model_path}: {e}")

        # Fallback to separate description file (for backward compatibility)
        description_file = os.path.join(model_path, "description.md")
        if os.path.exists(description_file):
            try:
                with open(description_file, 'r', encoding='utf-8') as f:
                    return f.read().strip()
            except Exception as e:
                print(f"Error loading description for {model_path}: {e}")

        # Fallback to .txt file
        description_file = os.path.join(model_path, "description.txt")
        if os.path.exists(description_file):
            try:
                with open(description_file, 'r', encoding='utf-8') as f:
                    return f.read().strip()
            except Exception as e:
                print(f"Error loading description for {model_path}: {e}")

        return None

    def load_model_images(self, model_path: str) -> List[Dict[str, str]]:
        """Load model images from images subdirectory"""
        images = []
        images_dir = os.path.join(model_path, "images")

        if not os.path.exists(images_dir):
            return images

        # Supported image formats
        image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg'}

        for filename in os.listdir(images_dir):
            file_path = os.path.join(images_dir, filename)
            if os.path.isfile(file_path):
                file_ext = os.path.splitext(filename)[1].lower()
                if file_ext in image_extensions:
                    # Check for caption file
                    caption_file = os.path.splitext(file_path)[0] + ".caption"
                    caption = ""
                    if os.path.exists(caption_file):
                        try:
                            with open(caption_file, 'r', encoding='utf-8') as f:
                                caption = f.read().strip()
                        except Exception:
                            pass

                    images.append({
                        'src': f"/assets/models/{os.path.basename(model_path)}/images/{filename}",
                        'alt': caption or f"{os.path.basename(model_path).title()} - {filename}",
                        'caption': caption,
                        'filename': filename
                    })

        # Sort images by filename for consistent ordering
        images.sort(key=lambda x: x['filename'])
        return images

    def load_model_metadata(self, model_path: str) -> Dict[str, str]:
        """Load model metadata from JSON file"""
        metadata_file = os.path.join(model_path, "metadata.json")
        if os.path.exists(metadata_file):
            try:
                with open(metadata_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading metadata for {model_path}: {e}")

        return {}

    def get_model_info(self, model_name: str) -> Dict:
        """Get information for a specific model"""
        return self.model_info.get(model_name, {
            'description': None,
            'images': [],
            'metadata': {}
        })

    def get_all_models_with_info(self) -> List[str]:
        """Get list of all models that have additional information"""
        return list(self.model_info.keys())

    def has_model_info(self, model_name: str) -> bool:
        """Check if a model has additional information"""
        return model_name in self.model_info

    def get_model_description(self, model_name: str) -> Optional[str]:
        """Get description for a specific model"""
        info = self.get_model_info(model_name)
        return info.get('description')

    def get_model_images(self, model_name: str) -> List[Dict[str, str]]:
        """Get images for a specific model"""
        info = self.get_model_info(model_name)
        return info.get('images', [])

    def get_model_metadata(self, model_name: str) -> Dict[str, str]:
        """Get metadata for a specific model"""
        info = self.get_model_info(model_name)
        return info.get('metadata', {})

# Global instance
model_info_manager = ModelInfoManager()