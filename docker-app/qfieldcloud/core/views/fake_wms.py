from django.contrib.auth.decorators import login_required
from django.http import HttpResponse

CAPABILITIES = """\
<?xml version='1.0' encoding="UTF-8" standalone="no"?>
<WMS_Capabilities version="1.3.0" xmlns="http://www.opengis.net/wms"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xmlns:xlink="http://www.w3.org/1999/xlink"
  xsi:schemaLocation="http://www.opengis.net/wms http://schemas.opengis.net/wms/1.3.0/capabilities_1_3_0.xsd">
  <Service>
    <Name>WMS</Name>
    <Title>Demo</Title>
    <Abstract></Abstract>
    <KeywordList></KeywordList>
    <OnlineResource xlink:href="http://example.org" />
  </Service>
  <Capability>
    <Request>
      <GetCapabilities>
        <Format>text/xml</Format>
        <DCPType>
          <HTTP>
            <Get><OnlineResource xlink:href="http://example.org" /></Get>
          </HTTP>
        </DCPType>
      </GetCapabilities>
      <GetMap>
        <Format>image/jpeg</Format>
        <DCPType>
          <HTTP>
            <Get><OnlineResource xlink:href="http://example.org" /></Get>
          </HTTP>
        </DCPType>
      </GetMap>
    </Request>
    <Exception>
      <Format>XML</Format>
    </Exception>
    <Layer>
      <Name>layers</Name>
      <Title>Layers</Title>
      <Layer>
        <Name>layer1</Name>
        <Title>Layer One</Title>
      </Layer>
      <Layer>
        <Name>layer2</Name>
        <Title>Layer Two</Title>
      </Layer>
    </Layer>
  </Capability>
</WMS_Capabilities>
"""


@login_required
def index(request):
    return HttpResponse(CAPABILITIES, content_type="text/xml")
