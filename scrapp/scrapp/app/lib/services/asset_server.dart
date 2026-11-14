import 'dart:io';

import 'package:flutter/services.dart';

/// Serves bundled `assets/web/**` over http://127.0.0.1 so the WebView can load ES modules
/// (module scripts are blocked from file:// URLs in Android WebView).
class LocalAssetServer {
  LocalAssetServer._();
  static HttpServer? _server;

  static Future<String> start() async {
    if (_server != null) return 'http://127.0.0.1:${_server!.port}';
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    _server = server;
    server.listen((req) async {
      var path = Uri.decodeComponent(req.uri.path);
      if (path == '/' || path.isEmpty) path = '/editor.html';
      if (path.contains('..')) {
        req.response.statusCode = HttpStatus.forbidden;
        await req.response.close();
        return;
      }
      try {
        final data = await rootBundle.load('assets/web$path');
        req.response.headers
          ..contentType = _type(path)
          ..set('Access-Control-Allow-Origin', '*')
          ..set('Cache-Control', 'no-cache');
        req.response.add(data.buffer.asUint8List(data.offsetInBytes, data.lengthInBytes));
      } catch (_) {
        req.response.statusCode = HttpStatus.notFound;
      }
      await req.response.close();
    });
    return 'http://127.0.0.1:${server.port}';
  }

  static ContentType _type(String path) {
    if (path.endsWith('.html')) return ContentType.html;
    if (path.endsWith('.js')) return ContentType('text', 'javascript', charset: 'utf-8');
    if (path.endsWith('.png')) return ContentType('image', 'png');
    if (path.endsWith('.jpg')) return ContentType('image', 'jpeg');
    if (path.endsWith('.glb')) return ContentType('model', 'gltf-binary');
    return ContentType.binary;
  }
}
