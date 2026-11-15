import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import 'package:share_plus/share_plus.dart';
import 'package:url_launcher/url_launcher.dart';

import '../state/library.dart';
import '../theme/palette.dart';
import '../theme/theme.dart';
import 'paper.dart';

/// The QR code image for a published collage link (made by the server: GET /c/TOKEN/qr.png).
String qrUrlFor(String publicUrl) => '${publicUrl.replaceAll(RegExp(r'/+$'), '')}/qr.png';

/// One tap: publishes the collage (an unlisted 3D link) and shows the link, a QR code, Copy and Share.
Future<void> showShareLinkSheet(BuildContext context, {required String collageId, required String title}) async {
  final lib = context.read<Library>();
  String url;
  try {
    url = await lib.publishCollage(collageId);
  } catch (e) {
    if (context.mounted) toast(context, 'Could not make the link: $e');
    return;
  }
  if (!context.mounted) return;
  await showModalBottomSheet(
    context: context,
    isScrollControlled: true,
    backgroundColor: Palette.card,
    shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(28))),
    builder: (ctx) => SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(22, 18, 22, 22),
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Text('SHARE IN 3D', style: ScrappType.display(28)),
          const SizedBox(height: 4),
          Text('Anyone with this link can look around "$title" in 3D. On Android phones they also get a View in AR button.',
              style: const TextStyle(color: Palette.inkSoft, fontWeight: FontWeight.w700)),
          const SizedBox(height: 14),
          Center(
            child: Container(
              width: 210,
              height: 210,
              padding: const EdgeInsets.all(8),
              decoration: BoxDecoration(color: Palette.card, borderRadius: BorderRadius.circular(18), border: Border.all(color: Palette.inkSoft.withValues(alpha: 0.25), width: 2)),
              child: Image.network(qrUrlFor(url), fit: BoxFit.contain,
                  errorBuilder: (_, __, ___) => const Center(child: Text('QR code unavailable', style: TextStyle(color: Palette.inkSoft))),
                  loadingBuilder: (_, child, p) => p == null ? child : const Center(child: CircularProgressIndicator(strokeWidth: 2))),
            ),
          ),
          const SizedBox(height: 12),
          SelectableText(url, textAlign: TextAlign.center, style: const TextStyle(fontWeight: FontWeight.w800)),
          const SizedBox(height: 14),
          Row(children: [
            Expanded(
              child: ScrappButton(
                label: 'Copy link',
                icon: Icons.copy_rounded,
                style: ScrappButtonStyle.quiet,
                expand: true,
                onPressed: () async {
                  await Clipboard.setData(ClipboardData(text: url));
                  if (ctx.mounted) toast(ctx, 'Link copied');
                },
              ),
            ),
            const SizedBox(width: 10),
            Expanded(child: ScrappButton(label: 'Share', icon: Icons.ios_share_rounded, expand: true, onPressed: () => Share.share(url, subject: title))),
          ]),
          const SizedBox(height: 8),
          TextButton.icon(
            icon: const Icon(Icons.open_in_new_rounded, size: 18),
            label: const Text('Open it in the browser', style: TextStyle(fontWeight: FontWeight.w800)),
            onPressed: () => launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication),
          ),
        ]),
      ),
    ),
  );
}
