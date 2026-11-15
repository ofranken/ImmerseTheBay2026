import 'package:scrapp/services/api.dart';

/// Scripted ApiClient: routes return canned JSON; `failing` makes every call throw (network down).
class FakeApi extends ApiClient {
  FakeApi() : super(baseUrl: 'http://fake');
  bool failing = false;
  final routes = <String, dynamic>{}; // "GET /stickers" -> json (or a function (body) -> json)
  final calls = <String>[];

  dynamic _hit(String method, String path, [Object? body]) {
    calls.add('$method $path');
    if (failing) throw Exception('network down');
    final key = '$method ${path.split('?').first}';
    if (!routes.containsKey(key)) throw ApiException(404, 'no route $key');
    final r = routes[key];
    return r is Function ? r(body) : r;
  }

  @override
  Future get(String path, {Map<String, String>? query}) async => _hit('GET', path);
  @override
  Future post(String path, [Object? body]) async => _hit('POST', path, body);
  @override
  Future patch(String path, Object body) async => _hit('PATCH', path, body);
  @override
  Future delete(String path) async => _hit('DELETE', path);
}
