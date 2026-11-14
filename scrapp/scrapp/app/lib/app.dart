import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'screens/auth_screen.dart';
import 'screens/home_shell.dart';
import 'state/app_state.dart';
import 'theme/theme.dart';

class ScrappApp extends StatelessWidget {
  const ScrappApp({super.key});

  @override
  Widget build(BuildContext context) {
    final signedIn = context.select<AppState, bool>((s) => s.signedIn);
    return MaterialApp(
      title: 'Scrapp',
      debugShowCheckedModeBanner: false,
      theme: buildTheme(),
      home: signedIn ? const HomeShell() : const AuthScreen(),
    );
  }
}
