import 'dart:html' as html;

Map<String, String> getLocationInfo() {
  final loc = html.window.location;
  return {
    'origin': loc.origin ?? '${loc.protocol}//${loc.host}',
    'protocol': loc.protocol ?? 'http:',
    'href': loc.href ?? '',
    'hostname': loc.hostname ?? '',
    'host': loc.host ?? ''
  };
}
