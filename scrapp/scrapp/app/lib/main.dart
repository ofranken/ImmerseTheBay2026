import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'app.dart';
import 'state/app_state.dart';
import 'state/glasses_state.dart';
import 'state/library.dart';
import 'state/social.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final app = AppState();
  await app.init();
  final library = Library(() => app.api);
  final social = Social(() => app.api);
  final glasses = GlassesState(app, library, social);
  runApp(MultiProvider(
    providers: [
      ChangeNotifierProvider.value(value: app),
      ChangeNotifierProvider.value(value: library),
      ChangeNotifierProvider.value(value: social),
      ChangeNotifierProvider.value(value: glasses),
    ],
    child: const ScrappApp(),
  ));
}
