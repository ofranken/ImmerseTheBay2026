import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../state/app_state.dart';
import '../theme/palette.dart';
import '../theme/theme.dart';
import '../widgets/paper.dart';
import 'settings_screen.dart';

class AuthScreen extends StatefulWidget {
  const AuthScreen({super.key});
  @override
  State<AuthScreen> createState() => _AuthScreenState();
}

class _AuthScreenState extends State<AuthScreen> {
  bool register = false;
  bool busy = false;
  final user = TextEditingController();
  final email = TextEditingController();
  final pass = TextEditingController();
  final invite = TextEditingController();

  Future<void> _go() async {
    setState(() => busy = true);
    final app = context.read<AppState>();
    try {
      if (register) {
        await app.register(user.text.trim(), email.text.trim(), pass.text, inviteCode: invite.text);
      } else {
        await app.signIn(user.text.trim(), pass.text);
      }
    } catch (e) {
      if (mounted) toast(context, '$e');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: PaperBackground(
        child: SafeArea(
          child: ListView(padding: const EdgeInsets.all(24), children: [
            Align(
              alignment: Alignment.topRight,
              child: IconButton(
                tooltip: 'Server settings',
                icon: const Icon(Icons.dns_rounded),
                onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const SettingsScreen(serverOnly: true))),
              ),
            ),
            const SizedBox(height: 24),
            Center(child: Text('Scrapp', style: ScrappType.wordmark(72))),
            const Center(child: Text('Say "scrapbook that". Keep the moment.', style: TextStyle(color: Palette.inkSoft, fontSize: 16))),
            const SizedBox(height: 36),
            PaperCard(
              padding: const EdgeInsets.all(20),
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                Text(register ? 'CREATE ACCOUNT' : 'WELCOME BACK', style: ScrappType.display(28)),
                const SizedBox(height: 16),
                TextField(controller: user, decoration: InputDecoration(labelText: register ? 'Username' : 'Username or email'), textInputAction: TextInputAction.next),
                if (register) ...[
                  const SizedBox(height: 12),
                  TextField(controller: email, decoration: const InputDecoration(labelText: 'Email'), keyboardType: TextInputType.emailAddress, textInputAction: TextInputAction.next),
                ],
                const SizedBox(height: 12),
                TextField(controller: pass, decoration: const InputDecoration(labelText: 'Password (8+ characters)'), obscureText: true, textInputAction: register ? TextInputAction.next : TextInputAction.done, onSubmitted: (_) => register ? null : _go()),
                if (register) ...[
                  const SizedBox(height: 12),
                  TextField(controller: invite, decoration: const InputDecoration(labelText: 'Invite code'), autocorrect: false, onSubmitted: (_) => _go()),
                ],
                const SizedBox(height: 20),
                ScrappButton(label: register ? 'Create account' : 'Sign in', icon: Icons.arrow_forward_rounded, onPressed: _go, busy: busy, expand: true),
                TextButton(
                  onPressed: () => setState(() => register = !register),
                  child: Text(register ? 'I already have an account' : 'New here? Create an account', style: const TextStyle(color: Palette.ink, fontWeight: FontWeight.w700)),
                ),
              ]),
            ),
          ]),
        ),
      ),
    );
  }
}
