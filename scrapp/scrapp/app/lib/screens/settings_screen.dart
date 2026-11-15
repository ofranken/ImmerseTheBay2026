import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../services/glasses_bridge.dart';
import '../state/app_state.dart';
import '../state/glasses_state.dart';
import '../theme/palette.dart';
import '../widgets/paper.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key, this.serverOnly = false});
  final bool serverOnly;
  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  late final server = TextEditingController(text: context.read<AppState>().api.baseUrl);

  Future<void> _perm(String p) async {
    final r = await GlassesBridge.requestPermission(p);
    if (mounted) toast(context, '$p: $r');
  }

  @override
  Widget build(BuildContext context) {
    final app = context.watch<AppState>();
    final g = context.watch<GlassesState>();
    final s = app.glasses;
    return Scaffold(
      appBar: AppBar(title: const Text('SETTINGS')),
      body: PaperBackground(
        child: ListView(padding: const EdgeInsets.all(18), children: [
          PaperCard(child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            const Text('Server', style: TextStyle(fontWeight: FontWeight.w900, fontSize: 17)),
            const SizedBox(height: 8),
            TextField(controller: server, decoration: const InputDecoration(labelText: 'API base URL', hintText: 'http://192.168.1.50:8000'), keyboardType: TextInputType.url),
            const SizedBox(height: 10),
            ScrappButton(label: 'Save server', icon: Icons.save_rounded, onPressed: () async {
              await app.setApiBase(server.text);
              if (context.mounted) toast(context, 'Server saved');
            }),
          ])),
          if (!widget.serverOnly) ...[
            const SectionTitle('Glasses'),
            PaperCard(child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Text('Status: ${g.registration.toLowerCase()} · session ${g.session.toLowerCase()}', style: const TextStyle(color: Palette.inkSoft)),
              const SizedBox(height: 10),
              Wrap(spacing: 8, runSpacing: 8, children: [
                ScrappButton(label: g.registered ? 'Unlink' : 'Link in Meta AI', icon: Icons.link_rounded, style: ScrappButtonStyle.quiet,
                    onPressed: () => g.registered ? GlassesBridge.unregister() : GlassesBridge.register()),
                ScrappButton(label: 'Camera access', icon: Icons.photo_camera_rounded, style: ScrappButtonStyle.quiet, onPressed: () => _perm('camera')),
                ScrappButton(label: 'Mic access', icon: Icons.mic_rounded, style: ScrappButtonStyle.quiet, onPressed: () => _perm('microphone')),
              ]),
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('Voice: "scrap that"'),
                subtitle: const Text('Transcribed on the glasses while Scrapp is running'),
                value: s.voice,
                onChanged: (v) => setState(() { s.voice = v; app.saveGlassesSettings(); }),
              ),
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('Capture button triggers Scrapp'),
                value: s.button,
                onChanged: (v) => setState(() { s.button = v; app.saveGlassesSettings(); }),
              ),
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('Fast shutter'),
                subtitle: const Text('Keeps a 2 fps camera stream open: ~1 s captures, more battery'),
                value: s.warmCamera,
                onChanged: (v) => setState(() { s.warmCamera = v; app.saveGlassesSettings(); }),
              ),
              const Text('Changes apply next time you start scrapbooking.', style: TextStyle(color: Palette.inkSoft)),
            ])),
            const SectionTitle('Developer'),
            PaperCard(child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('Mock glasses (no hardware)'),
                subtitle: const Text("Meta's MockDeviceKit pairs simulated Ray-Ban Meta glasses"),
                value: s.mockDevice,
                onChanged: (v) async {
                  setState(() => s.mockDevice = v);
                  await app.saveGlassesSettings();
                  await GlassesBridge.setMockDevice(v);
                  await g.refreshStatus();
                },
              ),
              if (s.mockDevice)
                ScrappButton(label: 'Simulate "scrap that"', icon: Icons.record_voice_over_rounded, style: ScrappButtonStyle.quiet,
                    onPressed: () => GlassesBridge.simulateTranscript('scrap that')),
            ])),
            const SizedBox(height: 24),
            ScrappButton(label: 'Sign out', icon: Icons.logout_rounded, style: ScrappButtonStyle.danger, onPressed: () async {
              await g.disarm();
              await app.signOut();
              if (context.mounted) Navigator.popUntil(context, (r) => r.isFirst);
            }),
          ],
        ]),
      ),
    );
  }
}
