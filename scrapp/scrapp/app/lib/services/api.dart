import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;
import 'package:http_parser/http_parser.dart';

class ApiException implements Exception {
  ApiException(this.status, this.message);
  final int status;
  final String message;
  @override
  String toString() => message;
}

/// JSON + multipart client for the FastAPI backend.
class ApiClient {
  ApiClient({required this.baseUrl, this.token});
  String baseUrl;
  String? token;

  Uri _u(String path, [Map<String, String>? q]) => Uri.parse('$baseUrl$path').replace(queryParameters: q);
  Map<String, String> get _h => {
        'Accept': 'application/json',
        if (token != null) 'Authorization': 'Bearer $token',
      };

  dynamic _decode(http.Response r) {
    final body = r.body.isEmpty ? null : jsonDecode(utf8.decode(r.bodyBytes));
    if (r.statusCode >= 400) {
      final detail = body is Map && body['detail'] != null ? body['detail'].toString() : 'Request failed (${r.statusCode})';
      throw ApiException(r.statusCode, detail);
    }
    return body;
  }

  Future<dynamic> get(String path, {Map<String, String>? query}) async =>
      _decode(await http.get(_u(path, query), headers: _h).timeout(const Duration(seconds: 30)));

  Future<dynamic> post(String path, [Object? body]) async => _decode(await http
      .post(_u(path), headers: {..._h, 'Content-Type': 'application/json'}, body: jsonEncode(body ?? {}))
      .timeout(const Duration(seconds: 60)));

  Future<dynamic> patch(String path, Object body) async => _decode(
      await http.patch(_u(path), headers: {..._h, 'Content-Type': 'application/json'}, body: jsonEncode(body)));

  Future<dynamic> delete(String path) async => _decode(await http.delete(_u(path), headers: _h));

  /// Multipart upload: one file field plus string fields.
  Future<dynamic> upload(
    String path, {
    String method = 'POST',
    required String fileField,
    String? filePath,
    Uint8List? bytes,
    String filename = 'image.jpg',
    String mime = 'image/jpeg',
    Map<String, String> fields = const {},
    Map<String, ({Uint8List bytes, String filename, String mime})> extraFiles = const {},
  }) async {
    final req = http.MultipartRequest(method, _u(path))
      ..headers.addAll(_h)
      ..fields.addAll(fields);
    final type = MediaType.parse(mime);
    if (filePath != null) {
      req.files.add(await http.MultipartFile.fromPath(fileField, filePath, contentType: type, filename: filename));
    } else if (bytes != null) {
      req.files.add(http.MultipartFile.fromBytes(fileField, bytes, contentType: type, filename: filename));
    }
    for (final e in extraFiles.entries) {
      req.files.add(http.MultipartFile.fromBytes(e.key, e.value.bytes, contentType: MediaType.parse(e.value.mime), filename: e.value.filename));
    }
    final streamed = await req.send().timeout(const Duration(seconds: 180));
    return _decode(await http.Response.fromStream(streamed));
  }
}
