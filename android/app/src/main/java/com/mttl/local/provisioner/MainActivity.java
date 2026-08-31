package com.mttl.local.provisioner;

import android.Manifest;
import android.app.Activity;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.net.NetworkRequest;
import android.net.wifi.ScanResult;
import android.net.wifi.WifiManager;
import android.net.wifi.WifiNetworkSpecifier;
import android.os.Build;
import android.os.Bundle;
import android.text.InputType;
import android.text.method.PasswordTransformationMethod;
import android.view.View;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.EditText;
import android.widget.ImageButton;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.TextView;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class MainActivity extends Activity {
    private static final int PERMISSION_REQUEST = 41;
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private WifiManager wifi;
    private ConnectivityManager connectivity;
    private Spinner homeSsid;
    private EditText homePassword;
    private Spinner deviceSpinner;
    private TextView status;
    private Button provisionButton;
    private ArrayAdapter<String> devices;
    private ArrayAdapter<String> homeNetworks;
    private ConnectivityManager.NetworkCallback callback;

    private final BroadcastReceiver scanReceiver = new BroadcastReceiver() {
        @Override public void onReceive(Context context, Intent intent) { showScanResults(); }
    };

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        wifi = (WifiManager) getApplicationContext().getSystemService(WIFI_SERVICE);
        connectivity = (ConnectivityManager) getSystemService(CONNECTIVITY_SERVICE);
        registerReceiver(scanReceiver, new IntentFilter(WifiManager.SCAN_RESULTS_AVAILABLE_ACTION));
        buildUi();
        requestPermissionsIfNeeded();
    }

    private void buildUi() {
        int pad = dp(20);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(pad, pad + dp(24), pad, pad);
        root.setBackgroundColor(Color.rgb(248, 250, 252));

        TextView title = text("MTTL-W01 Provisioner", 26, Color.rgb(20, 33, 61));
        title.setPadding(0, 0, 0, dp(8));
        root.addView(title);
        TextView help = text("Enable ASUS Router DNAT first. Hold the strip's main button for 10 seconds until its LED flashes rapidly.", 15, Color.DKGRAY);
        help.setPadding(0, 0, 0, dp(18));
        root.addView(help);

        Button scan = button("1. Scan Wi-Fi networks");
        scan.setOnClickListener(v -> startScan());
        root.addView(scan);

        root.addView(label("Home Wi-Fi SSID (2.4 GHz)"));
        homeNetworks = new ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item, new ArrayList<>());
        homeSsid = new Spinner(this);
        homeSsid.setAdapter(homeNetworks);
        homeSsid.setPadding(0, dp(8), 0, dp(8));
        root.addView(homeSsid);
        root.addView(label("Home Wi-Fi password"));
        homePassword = field(true);
        LinearLayout passwordRow = new LinearLayout(this);
        passwordRow.setOrientation(LinearLayout.HORIZONTAL);
        passwordRow.addView(homePassword, new LinearLayout.LayoutParams(0, dp(56), 1));
        ImageButton revealPassword = new ImageButton(this);
        revealPassword.setImageResource(android.R.drawable.ic_menu_view);
        revealPassword.setContentDescription("Show password");
        revealPassword.setBackgroundColor(Color.TRANSPARENT);
        revealPassword.setOnClickListener(v -> {
            boolean hidden = homePassword.getTransformationMethod() instanceof PasswordTransformationMethod;
            homePassword.setTransformationMethod(hidden ? null : PasswordTransformationMethod.getInstance());
            revealPassword.setContentDescription(hidden ? "Hide password" : "Show password");
            homePassword.setSelection(homePassword.length());
        });
        passwordRow.addView(revealPassword, new LinearLayout.LayoutParams(dp(56), dp(56)));
        root.addView(passwordRow);

        root.addView(label("Strip setup network"));
        devices = new ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item, new ArrayList<>());
        deviceSpinner = new Spinner(this);
        deviceSpinner.setAdapter(devices);
        deviceSpinner.setPadding(0, dp(8), 0, dp(8));
        root.addView(deviceSpinner);

        provisionButton = button("2. Provision");
        provisionButton.setOnClickListener(v -> provision());
        root.addView(provisionButton);
        status = text("Ready", 15, Color.DKGRAY);
        status.setPadding(0, dp(18), 0, dp(10));
        root.addView(status);

        TextView version = text("Version " + appVersion(), 11, Color.rgb(100, 116, 139));
        version.setGravity(android.view.Gravity.CENTER_HORIZONTAL);
        version.setPadding(0, dp(16), 0, dp(4));
        root.addView(version);

        ScrollView scroll = new ScrollView(this);
        scroll.addView(root);
        setContentView(scroll);
    }

    private TextView label(String value) {
        TextView view = text(value, 14, Color.rgb(71, 85, 105));
        view.setPadding(0, dp(12), 0, dp(4));
        return view;
    }

    private TextView text(String value, int size, int color) {
        TextView view = new TextView(this);
        view.setText(value);
        view.setTextSize(size);
        view.setTextColor(color);
        return view;
    }

    private EditText field(boolean password) {
        EditText view = new EditText(this);
        view.setSingleLine(true);
        if (password) view.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        return view;
    }

    private Button button(String value) {
        Button button = new Button(this);
        button.setText(value);
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, dp(52));
        params.setMargins(0, dp(12), 0, 0);
        button.setLayoutParams(params);
        return button;
    }

    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }

    private String appVersion() {
        try {
            return getPackageManager().getPackageInfo(getPackageName(), 0).versionName;
        } catch (PackageManager.NameNotFoundException error) {
            return "unknown";
        }
    }

    private void requestPermissionsIfNeeded() {
        List<String> missing = new ArrayList<>();
        if (checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED) missing.add(Manifest.permission.ACCESS_FINE_LOCATION);
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.NEARBY_WIFI_DEVICES) != PackageManager.PERMISSION_GRANTED) missing.add(Manifest.permission.NEARBY_WIFI_DEVICES);
        if (!missing.isEmpty()) requestPermissions(missing.toArray(new String[0]), PERMISSION_REQUEST);
    }

    private void startScan() {
        requestPermissionsIfNeeded();
        setStatus("Scanning nearby Wi-Fi networks…", false);
        if (!wifi.startScan()) showScanResults();
    }

    @SuppressWarnings("deprecation")
    private void showScanResults() {
        List<ScanResult> results;
        try { results = wifi.getScanResults(); }
        catch (SecurityException error) { setStatus("Nearby devices permission is required.", true); return; }
        Collections.sort(results, Comparator.comparingInt((ScanResult r) -> r.level).reversed());
        String selectedHome = homeSsid.getSelectedItem() == null ? "" : homeSsid.getSelectedItem().toString();
        homeNetworks.clear();
        devices.clear();
        for (ScanResult result : results) {
            String ssid = Build.VERSION.SDK_INT >= 33 ? result.getWifiSsid().toString().replace("\"", "") : result.SSID;
            if (ssid.isEmpty() || ssid.equals("<unknown ssid>")) continue;
            boolean setup = ssid.startsWith("ONLY_TAP_") || ssid.startsWith("TONLY_TAP_");
            if (setup && devices.getPosition(ssid) < 0) devices.add(ssid);
            if (!setup && result.frequency >= 2400 && result.frequency < 2500 && homeNetworks.getPosition(ssid) < 0) homeNetworks.add(ssid);
        }
        homeNetworks.notifyDataSetChanged();
        devices.notifyDataSetChanged();
        int prior = homeNetworks.getPosition(selectedHome);
        if (prior >= 0) homeSsid.setSelection(prior);
        if (homeNetworks.isEmpty()) setStatus("No 2.4 GHz home Wi-Fi network found.", true);
        else setStatus(devices.isEmpty() ? "Home networks found, but no strip setup network was found. Reset the strip and scan again." : "Select the home network and strip, then tap Provision.", devices.isEmpty());
    }

    private void provision() {
        String target = deviceSpinner.getSelectedItem() == null ? "" : deviceSpinner.getSelectedItem().toString();
        String ssid = homeSsid.getSelectedItem() == null ? "" : homeSsid.getSelectedItem().toString();
        String password = homePassword.getText().toString();
        if (target.isEmpty() || ssid.isEmpty()) { setStatus("Select a strip and enter the home Wi-Fi SSID.", true); return; }
        if (ssid.contains(":") || password.contains(":")) { setStatus("This firmware's local command cannot use ':' in the SSID or password.", true); return; }
        String suffix = target.substring(target.lastIndexOf('_') + 1);
        String setupPassword = "LGU_" + suffix;
        provisionButton.setEnabled(false);
        setStatus("Connecting to " + target + "… Approve the Android Wi-Fi prompt.", false);

        WifiNetworkSpecifier specifier = new WifiNetworkSpecifier.Builder().setSsid(target).setWpa2Passphrase(setupPassword).build();
        NetworkRequest request = new NetworkRequest.Builder()
                .addTransportType(NetworkCapabilities.TRANSPORT_WIFI)
                .removeCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
                .setNetworkSpecifier(specifier)
                .build();
        callback = new ConnectivityManager.NetworkCallback() {
            @Override public void onAvailable(Network network) {
                connectivity.bindProcessToNetwork(network);
                setStatus("Connected to strip. Reading device information…", false);
                worker.execute(() -> configureStrip(network, ssid, password));
            }
            @Override public void onUnavailable() { finishNetwork("Could not connect to the strip setup network.", true); }
            @Override public void onLost(Network network) { }
        };
        try {
            connectivity.requestNetwork(request, callback, 30000);
        } catch (SecurityException error) {
            finishNetwork("Android denied the network request permission. Reinstall the latest app and try again.", true);
        } catch (RuntimeException error) {
            finishNetwork("Could not start the Wi-Fi connection: " + error.getMessage(), true);
        }
    }

    private void configureStrip(Network network, String ssid, String password) {
        try {
            String info;
            try (Socket socket = network.getSocketFactory().createSocket()) {
                socket.connect(new InetSocketAddress("192.168.1.1", 30300), 7000);
                socket.setSoTimeout(2500);
                OutputStream out = socket.getOutputStream();
                out.write(binaryCommand(103));
                out.flush();
                info = readAvailable(socket.getInputStream());
            }
            runOnUiThread(() -> setStatus("Device found: " + summarizeInfo(info) + "\nSending home Wi-Fi settings…", false));
            String response;
            try (Socket socket = network.getSocketFactory().createSocket()) {
                socket.connect(new InetSocketAddress("192.168.1.1", 30300), 7000);
                socket.setSoTimeout(4000);
                OutputStream out = socket.getOutputStream();
                byte[] wifiCommand = binaryWifiCommand(ssid, password);
                out.write(wifiCommand, 0, 20);
                out.flush();
                // Firmware dispatches the 20-byte AP-mode header first and
                // then performs a separate receive for the 236-byte payload.
                Thread.sleep(100);
                out.write(wifiCommand, 20, wifiCommand.length - 20);
                out.flush();
                // Command 101 stores the Wi-Fi records. Command 102 then
                // restarts the strip so it joins the configured network.
                Thread.sleep(500);
                out.write(binaryCommand(102));
                out.flush();
                response = readAvailable(socket.getInputStream());
            }
            finishNetwork("Provision Success\nYou can close this APP", false);
        } catch (Exception error) {
            finishNetwork("Provisioning failed: " + error.getClass().getSimpleName() + ": " + error.getMessage(), true);
        }
    }

    private byte[] binaryCommand(int command) {
        ByteBuffer buffer = ByteBuffer.allocate(20).order(ByteOrder.LITTLE_ENDIAN);
        buffer.put("LGAPMODE0010".getBytes(StandardCharsets.US_ASCII));
        buffer.putInt(command);
        buffer.putInt(0);
        return buffer.array();
    }

    private byte[] binaryWifiCommand(String ssid, String password) {
        final int payloadLength = 236;
        ByteBuffer buffer = ByteBuffer.allocate(20 + payloadLength).order(ByteOrder.LITTLE_ENDIAN);
        buffer.put("LGAPMODE0010".getBytes(StandardCharsets.US_ASCII));
        buffer.putInt(101);
        buffer.putInt(payloadLength);
        putFixedUtf8(buffer, ssid, 32);
        putFixedUtf8(buffer, password, 32);
        // Firmware accepts two 64-byte Wi-Fi records.  Leave the fallback
        // record and the remaining reserved bytes zero-filled.
        buffer.position(buffer.capacity());
        return buffer.array();
    }

    private void putFixedUtf8(ByteBuffer buffer, String value, int fieldLength) {
        byte[] encoded = value.getBytes(StandardCharsets.UTF_8);
        int count = Math.min(encoded.length, fieldLength - 1);
        buffer.put(encoded, 0, count);
        buffer.position(buffer.position() + fieldLength - count);
    }

    private boolean isWifiConfigAccepted(String response) {
        if (response == null || response.isEmpty()) return false;
        byte[] bytes = response.getBytes(StandardCharsets.ISO_8859_1);
        if (bytes.length < 16) return false;
        String header = new String(bytes, 0, 12, StandardCharsets.US_ASCII);
        int command = bytes[12] & 0xff;
        return "LGAPMODE0010".equals(header) && command == 201;
    }

    private String responseHex(String response) {
        if (response == null || response.isEmpty()) return "empty";
        byte[] bytes = response.getBytes(StandardCharsets.ISO_8859_1);
        StringBuilder value = new StringBuilder();
        int limit = Math.min(bytes.length, 64);
        for (int index = 0; index < limit; index++) {
            if (index > 0) value.append(' ');
            value.append(String.format(java.util.Locale.US, "%02X", bytes[index] & 0xff));
        }
        return bytes.length + " bytes [" + value + "]";
    }

    private String readAvailable(InputStream input) throws Exception {
        ByteArrayOutputStream data = new ByteArrayOutputStream();
        byte[] buffer = new byte[512];
        try {
            int count;
            while ((count = input.read(buffer)) > 0) {
                data.write(buffer, 0, count);
                if (count < buffer.length) break;
            }
        } catch (java.net.SocketTimeoutException ignored) { }
        return new String(data.toByteArray(), StandardCharsets.ISO_8859_1).replace('\0', ' ').trim();
    }

    private String summarizeInfo(String raw) {
        String value = raw.replaceAll("[^A-Za-z0-9._-]+", " ").trim();
        return value.length() > 100 ? value.substring(0, 100) : value;
    }

    private void finishNetwork(String message, boolean error) {
        connectivity.bindProcessToNetwork(null);
        if (callback != null) {
            try { connectivity.unregisterNetworkCallback(callback); } catch (Exception ignored) { }
            callback = null;
        }
        runOnUiThread(() -> {
            provisionButton.setEnabled(true);
            setStatus(message, error);
        });
    }

    private void setStatus(String message, boolean error) {
        runOnUiThread(() -> {
            status.setText(message);
            status.setTextColor(error ? Color.rgb(185, 28, 28) : Color.rgb(30, 64, 175));
        });
    }

    @Override protected void onDestroy() {
        super.onDestroy();
        try { unregisterReceiver(scanReceiver); } catch (Exception ignored) { }
        if (callback != null) try { connectivity.unregisterNetworkCallback(callback); } catch (Exception ignored) { }
        connectivity.bindProcessToNetwork(null);
        worker.shutdownNow();
    }
}
