/*
indesign_export.jsx

InDesign automation:
- Export PNG preview
- Hide visible layers
- Save document
*/

function exportPreview(path)
{
    var doc = app.activeDocument;
    var file = new File(path);
    var options = new ExportOptionsPNG();
    options.exportResolution = 150;
    options.pngQuality = PNGQualityEnum.MAXIMUM;
    doc.exportFile(ExportFormat.PNG_FORMAT, file, false, options);
}

function hideVisibleLayers()
{
    var doc = app.activeDocument;
    for (var i = 0; i < doc.layers.length; i++)
    {
        processLayer(doc.layers[i]);
    }
}

function processLayer(layer)
{
    // Unlock first
    try { layer.locked = false; } catch (e) {}
    // Process sublayers
    if (layer.layers && layer.layers.length)
    {
        for (var i = 0; i < layer.layers.length; i++)
        {
            try { processLayer(layer.layers[i]); } catch (e) {}
        }
    }
    // Process page items
    try
    {
        if (layer.pageItems && layer.pageItems.length)
        {
            for (var j = 0; j < layer.pageItems.length; j++)
            {
                try { layer.pageItems[j].locked = false; } catch (e) {}
            }
        }
    }
    catch (e) {}
    // Hide if visible
    try
    {
        if (layer.visible)
        {
            layer.visible = false;
        }
    }
    catch (e) {}
}

function saveDocument()
{
    app.activeDocument.save();
}