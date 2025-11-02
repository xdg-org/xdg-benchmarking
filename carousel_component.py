from dash import html, dcc, Input, Output, callback
import dash_bootstrap_components as dbc

def create_image_carousel(images, carousel_id="model-carousel"):
    """Create a Bootstrap carousel for model images"""
    if not images:
        return html.Div("No images available for this model.", className="no-images-message")

    # Create carousel items
    carousel_items = []
    for i, image in enumerate(images):
        item = {
            "key": f"item-{i}",
            "src": image['src'],
            "alt": image['alt'],
            "caption": image['caption'] if image['caption'] else "",
            "img_style": {
                'width': '100%',
                'height': '300px',
                'objectFit': 'cover',
                'borderRadius': '8px'
            }
        }
        carousel_items.append(item)

    # Create the carousel
    carousel = dbc.Carousel(
        items=carousel_items,
        id=carousel_id,
        controls=True,
        indicators=True,
        interval=5000,  # Auto-advance every 5 seconds
        ride="carousel",
        className="model-carousel"
    )

    return carousel

def create_model_info_section(model_name, model_info_manager):
    """Create a complete model information section with description and carousel"""
    model_info = model_info_manager.get_model_info(model_name)
    description = model_info.get('description')
    images = model_info.get('images', [])
    metadata = model_info.get('metadata', {})

    if not description and not images:
        return None

    # Create description section
    description_section = None
    if description:
        description_section = html.Div([
            html.H4(f"{model_name.title()} Description", className="model-description-title"),
            html.Div(
                description,
                className="model-description-content",
                style={
                    'backgroundColor': '#f8f9fa',
                    'padding': '15px',
                    'borderRadius': '8px',
                    'borderLeft': '4px solid #3498db',
                    'marginBottom': '20px'
                }
            )
        ])

    # Create metadata section
    metadata_section = None
    if metadata:
        metadata_items = []
        for key, value in metadata.items():
            metadata_items.append(html.Div([
                html.Strong(f"{key.replace('_', ' ').title()}: "),
                html.Span(str(value))
            ], className="metadata-item"))

        metadata_section = html.Div([
            html.H5("Model Metadata", className="metadata-title"),
            html.Div(metadata_items, className="metadata-content")
        ], className="metadata-section")

    # Create carousel section
    carousel_section = None
    if images:
        carousel_section = html.Div([
            html.H4(f"{model_name.title()} Images", className="model-images-title"),
            create_image_carousel(images, f"carousel-{model_name}")
        ], className="carousel-section")

    # Combine all sections
    sections = [s for s in [description_section, metadata_section, carousel_section] if s is not None]

    if not sections:
        return None

    return html.Div([
        html.Hr(className="model-info-divider"),
        html.Div(sections, className="model-info-content")
    ], className="model-info-section")

def create_model_selector(model_info_manager, data_manager):
    """Create a model selector for showing model information"""
    models_with_info = model_info_manager.get_all_models_with_info()
    available_models = data_manager.models

    # Only show models that have both data and info
    models_to_show = [model for model in models_with_info if model in available_models]

    if not models_to_show:
        return None

    return html.Div([
        html.H3("Model Information", className="model-info-selector-title"),
        html.Div([
            html.Label("Select Model:", className="model-selector-label"),
            dcc.Dropdown(
                id='model-info-selector',
                options=[{'label': model.upper(), 'value': model} for model in models_to_show],
                value=models_to_show[0] if models_to_show else None,
                className="model-selector-dropdown"
            )
        ], className="model-selector-container"),
        html.Div(id='model-info-display', className="model-info-display")
    ], className="model-info-selector-section")

