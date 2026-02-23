import 'dart:convert';
import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:http_parser/http_parser.dart';
import 'package:flutter/services.dart';
// Conditional import to safely access browser location on web only
import 'src/location_info_io.dart'
    if (dart.library.html) 'src/location_info_web.dart' as location_info;

// Global JWT token storage
String? _globalJwtToken;

void main() => runApp(MyApp());

class MyApp extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Car Lease Assistant',
      theme: ThemeData(primarySwatch: Colors.blue),
      home: AppRoot(),
    );
  }
}

// AppRoot decides whether to show the login/register flow or the main HomePage.
class AppRoot extends StatefulWidget {
  @override
  _AppRootState createState() => _AppRootState();
}

class _AppRootState extends State<AppRoot> {
  bool _loggedIn = false;
  String? _username;

  void _onLogin(String username, String token) {
    setState(() {
      _loggedIn = true;
      _username = username;
      _globalJwtToken = token;
    });
  }

  void _onLogout() {
    setState(() {
      _loggedIn = false;
      _username = null;
      _globalJwtToken = null;
    });
  }

  @override
  Widget build(BuildContext context) {
    if (!_loggedIn) {
      return LoginPage(onLogin: _onLogin);
    }
    return HomePageWrapper(username: _username!, onLogout: _onLogout);
  }
}

// Simple wrapper to pass username and logout callback into HomePage
class HomePageWrapper extends StatelessWidget {
  final String username;
  final VoidCallback onLogout;
  HomePageWrapper({required this.username, required this.onLogout});

  @override
  Widget build(BuildContext context) {
    return HomePage();
  }
}

class LoginPage extends StatefulWidget {
  final void Function(String username, String token) onLogin;
  LoginPage({required this.onLogin});

  @override
  _LoginPageState createState() => _LoginPageState();
}

class _LoginPageState extends State<LoginPage> {
  final TextEditingController _userController = TextEditingController();
  final TextEditingController _passController = TextEditingController();
  bool _loading = false;

  Future<void> _login() async {
    final user = _userController.text.trim();
    final pass = _passController.text.trim();
    if (user.isEmpty || pass.isEmpty) return;
    setState(() => _loading = true);
    try {
      final resp = await http.post(Uri.parse('http://127.0.0.1:5000/login'),
          headers: {'Content-Type': 'application/json'}, body: json.encode({'username': user, 'password': pass}));
      if (resp.statusCode == 200) {
        final body = json.decode(resp.body);
        final token = body['token'] as String?;
        if (token != null && token.isNotEmpty) {
          widget.onLogin(user, token);
        } else {
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Login succeeded but no token received')));
        }
      } else {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Login failed')));
      }
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Login error')));
    } finally {
      setState(() => _loading = false);
    }
  }

  void _openRegister() {
    Navigator.of(context).push(MaterialPageRoute(builder: (_) => RegisterPage()));
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text('Login')),
      body: Padding(
        padding: EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            TextField(controller: _userController, decoration: InputDecoration(labelText: 'Username')),
            SizedBox(height: 8),
            TextField(controller: _passController, decoration: InputDecoration(labelText: 'Password'), obscureText: true),
            SizedBox(height: 16),
            ElevatedButton(onPressed: _loading ? null : _login, child: _loading ? CircularProgressIndicator() : Text('Login')),
            TextButton(onPressed: _openRegister, child: Text('Register')),
          ],
        ),
      ),
    );
  }
}

class RegisterPage extends StatefulWidget {
  @override
  _RegisterPageState createState() => _RegisterPageState();
}

class _RegisterPageState extends State<RegisterPage> {
  final TextEditingController _userController = TextEditingController();
  final TextEditingController _passController = TextEditingController();
  bool _loading = false;

  Future<void> _register() async {
    final user = _userController.text.trim();
    final pass = _passController.text.trim();
    if (user.isEmpty || pass.isEmpty) return;
    setState(() => _loading = true);
    try {
      final resp = await http.post(Uri.parse('http://127.0.0.1:5000/register'),
          headers: {'Content-Type': 'application/json'}, body: json.encode({'username': user, 'password': pass}));
      if (resp.statusCode == 200) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Registered. Please login.')));
        Navigator.of(context).pop();
      } else {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Register failed')));
      }
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Register error')));
    } finally {
      setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text('Register')),
      body: Padding(
        padding: EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            TextField(controller: _userController, decoration: InputDecoration(labelText: 'Username')),
            SizedBox(height: 8),
            TextField(controller: _passController, decoration: InputDecoration(labelText: 'Password'), obscureText: true),
            SizedBox(height: 16),
            ElevatedButton(onPressed: _loading ? null : _register, child: _loading ? CircularProgressIndicator() : Text('Register')),
          ],
        ),
      ),
    );
  }
}

class HomePage extends StatefulWidget {
  @override
  _HomePageState createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> with TickerProviderStateMixin {
  Map<String, dynamic>? _result;
  bool _loading = false;
  bool _showRaw = false;
  bool _fastMode = true;
  bool _jobPolling = false;
  late TabController _tabController;

  // Chat state
  List<Map<String, String>> _chatMessages = [];
  TextEditingController _chatInputController = TextEditingController();
  bool _chatLoading = false;

  // Multi-contract storage
  List<Map<String, dynamic>> _storedContracts = [];
  Map<String, dynamic>? _selectedContractForChat;

  // Comparison state
  bool _comparisonMode = false;
  List<Map<String, dynamic>> _selectedContractsForComparison = [];

  late String _apiBase;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 3, vsync: this);
    // Configure API base per platform:
    if (kIsWeb) {
      _apiBase = 'http://127.0.0.1:5000';
    } else if (Platform.isWindows || Platform.isLinux || Platform.isMacOS) {
      // For desktop builds (Windows/macOS/Linux) use localhost
      _apiBase = 'http://127.0.0.1:5000';
    } else {
      // For Android emulator use 10.0.2.2; for iOS simulator, localhost should work
      _apiBase = 'http://10.0.2.2:5000';
    }
    
    // Load saved leases on app startup if user is authenticated
    _loadSavedLeases();
  }

  @override
  void dispose() {
    _tabController.dispose();
    _chatInputController.dispose();
    super.dispose();
  }

  // Load saved leases from backend on app startup
  Future<void> _loadSavedLeases() async {
    if (_globalJwtToken == null || _globalJwtToken!.isEmpty) {
      print('[DEBUG] No JWT token available; skipping load saved leases');
      return;
    }

    try {
      final resp = await http.get(
        Uri.parse('$_apiBase/my_leases'),
        headers: {
          'Authorization': 'Bearer $_globalJwtToken',
          'Content-Type': 'application/json',
        },
      ).timeout(Duration(seconds: 10));

      if (resp.statusCode == 200) {
        final body = json.decode(resp.body);
        final leases = body['leases'] as List? ?? [];
        
        _safeSetState(() {
          _storedContracts = leases.map((lease) {
            // Backend returns complete lease data directly (already parsed from extracted_json)
            final typedLease = convertToTypedMap(lease) as Map<String, dynamic>;
            print('[DEBUG] Loaded lease: keys=${typedLease.keys.toList()}');
            return <String, dynamic>{
              ...typedLease,
              'saved_name': typedLease['file_name'] ?? 'Lease',
              'saved_at': typedLease['uploaded_at'] ?? '',
              'lease_id': typedLease['lease_id'],
            };
          }).toList().cast<Map<String, dynamic>>();
        });
        
        print('[DEBUG] Loaded ${_storedContracts.length} saved leases from backend');
      } else if (resp.statusCode == 401) {
        print('[DEBUG] Unauthorized - JWT token may have expired');
      } else {
        print('[DEBUG] Failed to load saved leases: ${resp.statusCode}');
      }
    } catch (e) {
      print('[DEBUG] Error loading saved leases: $e');
    }
  }

  // Safe setState helper to avoid calling setState after dispose
  void _safeSetState(VoidCallback fn) {
    if (!mounted) return;
    setState(fn);
  }

  // Convert dynamic decoded JSON (which may be a LinkedHashMap<dynamic,dynamic>)
  // into typed Dart collections with `String` keys. This handles nested Maps
  // and Lists recursively so callers can safely cast to `Map<String, dynamic>`.
  dynamic convertToTypedMap(dynamic input) {
    if (input == null) return null;
    if (input is Map) {
      final out = <String, dynamic>{};
      input.forEach((k, v) {
        final key = k?.toString() ?? '';
        out[key] = convertToTypedMap(v);
      });
      return out;
    }
    if (input is List) {
      return input.map((e) => convertToTypedMap(e)).toList();
    }
    return input;
  }

  // Backwards-compatible private alias used elsewhere in this file.
  dynamic _convertToTypedMap(dynamic input) => convertToTypedMap(input);

  Future<void> _pickAndUploadPdf() async {
    _safeSetState(() {
      _loading = true;
      _result = null;
    });

    try {
      FilePickerResult? pickResult = await FilePicker.platform.pickFiles(
        type: FileType.custom,
        allowedExtensions: ['pdf'],
        withData: kIsWeb,
      );

      if (pickResult == null || pickResult.files.isEmpty) {
        _safeSetState(() => _loading = false);
        return;
      }

      final picked = pickResult.files.single;
      final uri = Uri.parse('$_apiBase/process_lease_pdf?fast_mode=${_fastMode ? 'true' : 'false'}');

      final request = http.MultipartRequest('POST', uri);
      
      // Add JWT token to Authorization header
      if (_globalJwtToken != null && _globalJwtToken!.isNotEmpty) {
        request.headers['Authorization'] = 'Bearer $_globalJwtToken';
      }

      if (kIsWeb || picked.path == null) {
        final bytes = picked.bytes;
        if (bytes == null) {
          throw Exception('Picked file has no byte data.');
        }
        request.files.add(
          http.MultipartFile.fromBytes(
            'file',
            bytes,
            filename: picked.name,
            contentType: MediaType('application', 'pdf'),
          ),
        );
      } else {
        final file = File(picked.path!);
        request.files.add(await http.MultipartFile.fromPath('file', file.path));
      }

      final streamed = await request.send();
      final resp = await http.Response.fromStream(streamed);

      if (resp.statusCode == 200) {
        // Decode JSON response and immediately convert to typed Map
        Map<String, dynamic>? body;
        try {
          final rawBody = json.decode(resp.body);
          // Convert LinkedHashMap to typed Map immediately to avoid type warnings
          body = convertToTypedMap(rawBody) as Map<String, dynamic>;
          print('[DEBUG] Upload response parsed. Status: ${body?['status']}, Job ID: ${body?['job_id']}');
          print('[DEBUG] Response keys: ${body?.keys.toList()}');
          print('[DEBUG] extracted_text length: ${(body?['extracted_text'] as String?)?.length}');
          print('[DEBUG] full_extraction keys: ${(body?['full_extraction'] as Map?)?.keys.toList()}');
        } catch (e) {
          // Silently log, do not show to user
          debugPrint('JSON decode error: $e');
          print('[DEBUG] JSON decode error: $e');
        }
        
        // If server returned a job_id, start polling for heavy analysis
        if (body != null && body['job_id'] != null && body['status'] == 'pending') {
          _safeSetState(() {
            _result = body; // quick fields
            _jobPolling = true;
            print('[DEBUG] After immediate assignment, _result keys: ${_result?.keys.toList()}');
            print('[DEBUG] After immediate assignment, _result["extracted_text"] length: ${(_result?['extracted_text'] as String?)?.length}');
          });
          _pollJobStatus(body['job_id'].toString());
        } else if (body != null) {
          _safeSetState(() {
            _result = body;
            print('[DEBUG] Non-polling assignment, _result keys: ${_result?.keys.toList()}');
          });
        } else if (body == null) {
          // If body is still null after conversion, set empty result silently
          _safeSetState(() {
            _result = {};
            print('[DEBUG] Body was null; set empty result');
          });
        }
      } else {
        // Only show error SnackBar for actual HTTP errors
        final errorMsg = 'Server error (${resp.statusCode}). Please try again.';
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(errorMsg), duration: Duration(seconds: 3)),
        );
      }
    } catch (e) {
      // Silently catch all errors; do not show error dialogs to user
      debugPrint('Upload error: $e');
    } finally {
      _safeSetState(() => _loading = false);
    }
  }

  Future<void> _pollJobStatus(String jobId) async {
    final statusUrl = '$_apiBase/analysis_status/$jobId';
    final start = DateTime.now();
    print('[DEBUG] Starting poll for job $jobId');
    try {
      while (true) {
        final resp = await http.get(
          Uri.parse(statusUrl),
          headers: {
            if (_globalJwtToken != null && _globalJwtToken!.isNotEmpty)
              'Authorization': 'Bearer $_globalJwtToken',
            'Content-Type': 'application/json',
          },
        ).timeout(Duration(seconds: 10));
        if (resp.statusCode == 200) {
          try {
            final rawData = json.decode(resp.body);
            // Convert to typed Map immediately
            final data = convertToTypedMap(rawData) as Map<String, dynamic>;
            final status = data['status'];
            print('[DEBUG] Poll response status: $status');
            if (status == 'done') {
              // Merge results into existing _result
              final rawResult = data['result'];
              final Map<String, dynamic> result = convertToTypedMap(rawResult) as Map<String, dynamic>;
              print('[DEBUG] Poll done. Result keys: ${result.keys.toList()}');
              print('[DEBUG] Result full_extraction keys: ${(result['full_extraction'] as Map?)?.keys.toList()}');
              _safeSetState(() {
                // Update full_extraction, negotiation_advice, fairness_analysis if present
                if (_result == null) _result = {};
                _result = {...?_result, ...result};
                _jobPolling = false;
                print('[DEBUG] After poll merge, _result keys: ${_result?.keys.toList()}');
                print('[DEBUG] After poll merge, _result["full_extraction"] keys: ${(_result?['full_extraction'] as Map?)?.keys.toList()}');
              });
              return;
            } else if (status == 'error') {
              print('[DEBUG] Poll returned error status');
              _safeSetState(() {
                _jobPolling = false;
              });
              // Silently exit; do not show error to user
              return;
            }
          } catch (parseErr) {
            debugPrint('Poll JSON parse error: $parseErr');
            print('[DEBUG] Poll parse error: $parseErr');
            // Continue polling on parse error
          }
        } else if (resp.statusCode == 404) {
          print('[DEBUG] Poll got 404 - job not found');
          _safeSetState(() => _jobPolling = false);
          // Job not found, silently stop polling
          return;
        }

        // Timeout guard: stop polling after 2 minutes
        if (DateTime.now().difference(start).inSeconds > 120) {
          print('[DEBUG] Poll timeout after 2 minutes');
          _safeSetState(() => _jobPolling = false);
          // Silently stop; do not show timeout message to user
          return;
        }

        await Future.delayed(Duration(seconds: 2));
      }
    } catch (e) {
      // Silently catch polling timeout or network errors
      print('[DEBUG] Polling exception: $e');
      _safeSetState(() => _jobPolling = false);
      debugPrint('Polling error: $e');
    }
  }

  void _saveCurrentContract() {
    if (_result == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('No contract to save. Upload a PDF first.')),
      );
      return;
    }

    // Create a copy with a timestamp and name
    final contractName = 'Contract ${_storedContracts.length + 1} - ${DateTime.now().toString().split(' ')[0]}';
    final savedContract = {
      ..._result!,
      'saved_name': contractName,
      'saved_at': DateTime.now().toIso8601String(),
    };

    _safeSetState(() {
      _storedContracts.add(savedContract);
    });

    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('Contract saved as "$contractName"')),
    );
  }

  void _showComparisonDialog() {
    if (_selectedContractsForComparison.length < 2) return;

    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('Contract Comparison'),
        content: SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('Comparing ${_selectedContractsForComparison.length} contracts:', style: TextStyle(fontWeight: FontWeight.bold)),
              SizedBox(height: 16),
              ..._selectedContractsForComparison.map((contract) {
                final fullExtraction = contract['full_extraction'] as Map<String, dynamic>? ?? {};
                final fairnessAnalysis = contract['fairness_analysis'] as Map<String, dynamic>? ?? {};
                final dealRating = fairnessAnalysis['deal_rating'] ?? fairnessAnalysis['DealRating'] ?? fairnessAnalysis['dealRating'] ?? fairnessAnalysis['fairness_score'];
                final contractName = contract['saved_name'] ?? 'Unnamed Contract';

                return Card(
                  margin: EdgeInsets.only(bottom: 12),
                  child: Padding(
                    padding: EdgeInsets.all(12),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(contractName, style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
                        SizedBox(height: 8),
                        Text('Vehicle: ${fullExtraction['make'] ?? 'Unknown'} ${fullExtraction['model'] ?? 'Model'} (${fullExtraction['year'] ?? 'Year'})'),
                        if (fullExtraction['monthly_payment'] != null) Text('Monthly Payment: \$${fullExtraction['monthly_payment']}'),
                        if (fullExtraction['total_lease_cost'] != null) Text('Total Lease Cost: \$${fullExtraction['total_lease_cost']}'),
                        if (fullExtraction['down_payment'] != null) Text('Down Payment: \$${fullExtraction['down_payment']}'),
                        if (fullExtraction['lease_term_months'] != null) Text('Lease Term: ${fullExtraction['lease_term_months']} months'),
                        if (dealRating != null) Text('Deal Rating: $dealRating'),
                      ],
                    ),
                  ),
                );
              }).toList(),
              SizedBox(height: 16),
              Text('Analysis:', style: TextStyle(fontWeight: FontWeight.bold)),
              SizedBox(height: 8),
              ..._generateComparisonAnalysis(),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: Text('Close'),
          ),
        ],
      ),
    );
  }

  List<Widget> _generateComparisonAnalysis() {
    if (_selectedContractsForComparison.length < 2) return [];

    final analyses = <Widget>[];

    // Compare monthly payments
    final payments = _selectedContractsForComparison.map((c) {
      final fullExtraction = c['full_extraction'] as Map<String, dynamic>? ?? {};
      return {
        'name': c['saved_name'] ?? 'Unnamed',
        'payment': double.tryParse(fullExtraction['monthly_payment']?.toString() ?? '0') ?? 0,
      };
    }).toList();

    payments.sort((a, b) => a['payment'].compareTo(b['payment']));

    if (payments.first['payment'] > 0) {
      analyses.add(Text('💰 Lowest Monthly Payment: ${payments.first['name']} (\$${payments.first['payment']})'));
      analyses.add(Text('💸 Highest Monthly Payment: ${payments.last['name']} (\$${payments.last['payment']})'));
    }

    // Compare total costs
    final costs = _selectedContractsForComparison.map((c) {
      final fullExtraction = c['full_extraction'] as Map<String, dynamic>? ?? {};
      return {
        'name': c['saved_name'] ?? 'Unnamed',
        'cost': double.tryParse(fullExtraction['total_lease_cost']?.toString() ?? '0') ?? 0,
      };
    }).toList();

    costs.sort((a, b) => a['cost'].compareTo(b['cost']));

    if (costs.first['cost'] > 0) {
      analyses.add(Text('✅ Lowest Total Cost: ${costs.first['name']} (\$${costs.first['cost']})'));
      analyses.add(Text('❌ Highest Total Cost: ${costs.last['name']} (\$${costs.last['cost']})'));
    }

    // Compare deal ratings
    final ratings = _selectedContractsForComparison.map((c) {
      final fairnessAnalysis = c['fairness_analysis'] as Map<String, dynamic>? ?? {};
      final dealRating = fairnessAnalysis['deal_rating'] ?? fairnessAnalysis['DealRating'] ?? fairnessAnalysis['dealRating'] ?? fairnessAnalysis['fairness_score'];
      return {
        'name': c['saved_name'] ?? 'Unnamed',
        'rating': dealRating is num ? dealRating.toDouble() : double.tryParse(dealRating?.toString() ?? '0') ?? 0,
      };
    }).toList();

    ratings.sort((a, b) => b['rating'].compareTo(a['rating'])); // Highest first

    if (ratings.first['rating'] > 0) {
      analyses.add(Text('🏆 Best Deal Rating: ${ratings.first['name']} (${ratings.first['rating']})'));
      analyses.add(Text('⚠️ Worst Deal Rating: ${ratings.last['name']} (${ratings.last['rating']})'));
    }

    return analyses.map((w) => Padding(padding: EdgeInsets.only(bottom: 4), child: w)).toList();
  }

  Future<void> _sendChatMessage() async {
    if (_chatInputController.text.trim().isEmpty) return;
    
    // Check if we have a selected contract for chat
    final contractForChat = _selectedContractForChat ?? _result;
    if (contractForChat == null || contractForChat['job_id'] == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Please select a contract for chat first')),
      );
      return;
    }

    final userMessage = _chatInputController.text.trim();
    final jobId = contractForChat['job_id'].toString();
    
    _safeSetState(() {
      _chatMessages.add({'role': 'user', 'text': userMessage});
      _chatLoading = true;
    });
    _chatInputController.clear();

    try {
      // Call the correct endpoint with job_id, including JWT token
      final response = await http.post(
        Uri.parse('$_apiBase/chat/$jobId'),
        headers: {
          'Content-Type': 'application/json',
          if (_globalJwtToken != null && _globalJwtToken!.isNotEmpty)
            'Authorization': 'Bearer $_globalJwtToken',
        },
        body: jsonEncode({
          'message': userMessage,
        }),
      ).timeout(Duration(seconds: 30));

      if (response.statusCode == 200) {
        final result = jsonDecode(response.body);
        // Server returns 'reply', not 'response'
        final botResponse = result['reply'] ?? result['response'] ?? 'No response';
        _safeSetState(() {
          _chatMessages.add({'role': 'bot', 'text': botResponse});
        });
      } else if (response.statusCode == 404) {
        _safeSetState(() {
          _chatMessages.add({'role': 'bot', 'text': 'Error: Chat context not found. Please upload the lease PDF again.'});
        });
      } else {
        String errorMsg = 'Chat error';
        try {
          final errorData = jsonDecode(response.body);
          errorMsg = errorData['error'] ?? errorData['message'] ?? 'Chat error';
        } catch (_) {}
        _safeSetState(() {
          _chatMessages.add({'role': 'bot', 'text': 'Error: $errorMsg'});
        });
      }
    } catch (e) {
      _safeSetState(() {
        _chatMessages.add({'role': 'bot', 'text': 'Connection error: ${e.toString()}'});
      });
    } finally {
      _safeSetState(() => _chatLoading = false);
    }
  }

  Future<void> _testConnection() async {
    final hosts = [
      _apiBase.replaceAll(RegExp(r'/?$'), ''),
      'http://127.0.0.1:5000',
      'http://192.168.1.9:5000',
      'http://[::1]:5000'
    ];

    final results = <String, String>{};

    for (final host in hosts) {
      final getTarget = Uri.parse('$host/health');
      try {
        final resp = await http.get(getTarget).timeout(Duration(seconds: 5));
        results[host] = 'GET ${resp.statusCode}';
      } catch (e) {
        results[host] = 'GET ERR: ${e.toString()}';
      }

      try {
        final client = http.Client();
        final req = http.Request('OPTIONS', getTarget);
        req.headers['Content-Type'] = 'application/json';
        final streamed = await client.send(req).timeout(Duration(seconds: 5));
        results[host] = '${results[host]} | OPTIONS ${streamed.statusCode}';
      } catch (e) {
        results[host] = '${results[host]} | OPTIONS ERR: ${e.toString()}';
      }
    }

    final location = location_info.getLocationInfo();
    final buffer = StringBuffer();
    buffer.writeln('Browser location origin: ${location['origin']}');
    buffer.writeln('Browser protocol: ${location['protocol']}');
    buffer.writeln('\nConnection probe results:');

    results.forEach((k, v) {
      buffer.writeln('$k -> $v');
      if (kIsWeb && (location['protocol']?.toLowerCase() ?? '').startsWith('https') && k.startsWith('http://')) {
        buffer.writeln('  ⚠️ Warning: Mixed-content risk.');
      }
    });

    print(buffer.toString());

    await showDialog(context: context, builder: (_) => AlertDialog(
      title: Text('Connection Probe Results'),
      content: SingleChildScrollView(child: SelectableText(buffer.toString())),
      actions: [TextButton(onPressed: () => Navigator.of(context).pop(), child: Text('OK'))],
    ));
  }

  // Helper method to get color based on deal rating
  Color _getRatingColor(dynamic rating) {
    if (rating == null) return Colors.grey;
    final ratingStr = rating.toString();
    final ratingNum = double.tryParse(ratingStr) ?? 0;
    if (ratingNum >= 8) return Colors.green;
    if (ratingNum >= 5) return Colors.orange;
    return Colors.red;
  }

  // Helper method to get icon based on deal rating
  IconData _getRatingIcon(dynamic rating) {
    if (rating == null) return Icons.help_outline;
    final ratingStr = rating.toString();
    final ratingNum = double.tryParse(ratingStr) ?? 0;
    if (ratingNum >= 8) return Icons.thumb_up;
    if (ratingNum >= 5) return Icons.thumbs_up_down;
    return Icons.thumb_down;
  }

  Widget _buildAnalysisView() {
    print('[DEBUG] _buildAnalysisView called. _result is ${_result == null ? 'null' : 'not null'}, _jobPolling: $_jobPolling');
    if (_result != null) {
      print('[DEBUG] _result keys: ${_result!.keys.toList()}');
      print('[DEBUG] _result["full_extraction"] is ${_result!['full_extraction'] == null ? 'null' : 'not null'}');
      if (_result!['full_extraction'] != null) {
        final fe = _result!['full_extraction'] as Map?;
        print('[DEBUG] full_extraction keys: ${fe?.keys.toList()}');
        print('[DEBUG] full_extraction lessee_name: ${fe?['lessee_name']}');
        print('[DEBUG] full_extraction lessor_name: ${fe?['lessor_name']}');
      }
    }
    
    // If there's no result yet, either show spinner when uploading/polling
    // or a friendly empty state prompting the user to upload.
    if (_result == null) {
      if (_loading || _jobPolling) {
        return Center(
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              SizedBox(
                width: 80,
                height: 80,
                child: CircularProgressIndicator(
                  strokeWidth: 6,
                  valueColor: AlwaysStoppedAnimation<Color>(Colors.blue),
                ),
              ),
              SizedBox(height: 24),
              Text(
                _loading ? 'Uploading and extracting lease data...' : 'Running deeper analysis...',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.w500, color: Colors.grey[700]),
                textAlign: TextAlign.center,
              ),
              SizedBox(height: 8),
              Text(
                'This may take a moment',
                style: TextStyle(fontSize: 14, color: Colors.grey[500]),
                textAlign: TextAlign.center,
              ),
            ],
          ),
        );
      }

      // No upload in progress and no result -> show placeholder prompting upload
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24.0),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(Icons.upload_file, size: 64, color: Colors.grey[400]),
              SizedBox(height: 16),
              Text('No lease loaded', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w600, color: Colors.grey[800])),
              SizedBox(height: 8),
              Text('Upload a lease PDF to extract terms and run the analysis.', textAlign: TextAlign.center, style: TextStyle(color: Colors.grey[600])),
            ],
          ),
        ),
      );
    }

    final fullExtraction = convertToTypedMap((_result!['full_extraction'] ?? {})) as Map<String, dynamic>;
    final datapoints = convertToTypedMap((_result!['lease_datapoints'] ?? {})) as Map<String, dynamic>;
    final fairnessAnalysis = convertToTypedMap((_result!['fairness_analysis'] ?? {})) as Map<String, dynamic>;
    final negotiationAdvice = convertToTypedMap((_result!['negotiation_advice'] ?? {})) as Map<String, dynamic>;

    print('[DEBUG] fairnessAnalysis keys: ${fairnessAnalysis.keys.toList()}');
    print('[DEBUG] fairnessAnalysis content: $fairnessAnalysis');

    // Extract deal rating from fairness analysis
    final dealRating = fairnessAnalysis['deal_rating'] ?? fairnessAnalysis['DealRating'] ?? fairnessAnalysis['dealRating'] ?? fairnessAnalysis['fairness_score'];
    final finalSummary = fairnessAnalysis['final_summary'] ?? fairnessAnalysis['FinalSummary'] ?? fairnessAnalysis['finalSummary'] ?? fairnessAnalysis['summary'];

    print('[DEBUG] dealRating: $dealRating');
    print('[DEBUG] finalSummary: $finalSummary');

    Widget _sectionCard(String title, IconData icon, Color iconColor, List<Widget> children) {
      return Card(
        margin: EdgeInsets.symmetric(vertical: 8),
        elevation: 4,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        child: Container(
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(16),
            gradient: LinearGradient(
              begin: Alignment.topLeft,
              end: Alignment.bottomRight,
              colors: [
                Colors.white,
                Colors.grey[50]!,
              ],
            ),
          ),
          padding: const EdgeInsets.all(16.0),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Container(
                padding: EdgeInsets.all(8),
                decoration: BoxDecoration(
                  color: iconColor.withOpacity(0.1),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Icon(icon, color: iconColor, size: 24),
              ),
              SizedBox(width: 12),
              Text(title, style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: Colors.grey[800])),
            ]),
            SizedBox(height: 16),
            ...children
          ]),
        ),
      );
    }

    Widget _infoRow(String label, dynamic value, {Color? valueColor, IconData? prefixIcon}) {
      if (value == null || value.toString().isEmpty || value.toString() == 'null') return SizedBox.shrink();
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 8.0),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          if (prefixIcon != null) ...[
            Icon(prefixIcon, size: 18, color: Colors.grey[500]),
            SizedBox(width: 8),
          ],
          SizedBox(
            width: 140,
            child: Text(label, style: TextStyle(fontWeight: FontWeight.w600, color: Colors.grey[600], fontSize: 14)),
          ),
          Expanded(
            child: Text(
              value.toString(),
              style: TextStyle(
                color: valueColor ?? Colors.grey[900],
                fontWeight: valueColor != null ? FontWeight.bold : FontWeight.normal,
                fontSize: 14,
              ),
            ),
          ),
        ]),
      );
    }

    // Build deal score card if available
    Widget _buildDealScoreCard() {
      if (fairnessAnalysis.containsKey('error')) {
        return Card(
          margin: EdgeInsets.symmetric(vertical: 12),
          elevation: 8,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(24)),
          child: Container(
            padding: EdgeInsets.all(24),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(24),
              color: Colors.red[50],
            ),
            child: Column(children: [
              Icon(Icons.error_outline, color: Colors.red[700], size: 48),
              SizedBox(height: 16),
              Text('Analysis Error', style: TextStyle(color: Colors.red[700], fontSize: 20, fontWeight: FontWeight.bold)),
              SizedBox(height: 8),
              Text(
                fairnessAnalysis['error']?.toString() ?? 'Unknown error occurred during fairness analysis',
                style: TextStyle(color: Colors.red[600], fontSize: 14),
                textAlign: TextAlign.center,
              ),
            ]),
          ),
        );
      }
      
      if (dealRating == null) {
        if (_jobPolling) {
          return Card(
            margin: EdgeInsets.symmetric(vertical: 12),
            elevation: 8,
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(24)),
            child: Container(
              padding: EdgeInsets.all(24),
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(24),
                color: Colors.grey[100],
              ),
              child: Column(children: [
                SizedBox(width: 48, height: 48, child: CircularProgressIndicator(color: Colors.grey[600])),
                SizedBox(height: 16),
                Text('Analyzing Fairness...', style: TextStyle(color: Colors.grey[700], fontSize: 20, fontWeight: FontWeight.bold)),
                SizedBox(height: 8),
                Text(
                  'Please wait while we calculate the fairness score',
                  style: TextStyle(color: Colors.grey[600], fontSize: 14),
                  textAlign: TextAlign.center,
                ),
              ]),
            ),
          );
        }
        // Show default score if analysis completed but no score found
        final defaultScore = 5.0;
        final defaultPercent = 0.5;
        return Card(
          margin: EdgeInsets.symmetric(vertical: 12),
          elevation: 8,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(24)),
          child: Container(
            padding: EdgeInsets.all(24),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(24),
              gradient: LinearGradient(
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
                colors: [
                  _getRatingColor(defaultScore).withOpacity(0.85),
                  _getRatingColor(defaultScore),
                ],
              ),
              boxShadow: [
                BoxShadow(
                  color: _getRatingColor(defaultScore).withOpacity(0.3),
                  blurRadius: 16,
                  offset: Offset(0, 8),
                )
              ],
            ),
            child: Column(children: [
              Text('Deal Fairness Score', style: TextStyle(color: Colors.white70, fontSize: 16, fontWeight: FontWeight.w500)),
              SizedBox(height: 16),
              Stack(alignment: Alignment.center, children: [
                Container(
                  width: 120,
                  height: 120,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: Colors.white.withOpacity(0.15),
                    border: Border.all(color: Colors.white.withOpacity(0.4), width: 3),
                  ),
                ),
                SizedBox(
                  width: 120,
                  height: 120,
                  child: CircularProgressIndicator(
                    value: defaultPercent,
                    strokeWidth: 8,
                    valueColor: AlwaysStoppedAnimation<Color>(Colors.white),
                    backgroundColor: Colors.white.withOpacity(0.2),
                  ),
                ),
                Column(mainAxisAlignment: MainAxisAlignment.center, children: [
                  Text(
                    defaultScore.toStringAsFixed(1),
                    style: TextStyle(
                      fontSize: 44,
                      fontWeight: FontWeight.bold,
                      color: Colors.white,
                    ),
                  ),
                  Text('/10', style: TextStyle(color: Colors.white70, fontSize: 14)),
                ]),
              ]),
              SizedBox(height: 20),
              Container(
                padding: EdgeInsets.all(14),
                decoration: BoxDecoration(
                  color: Colors.white.withOpacity(0.15),
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(color: Colors.white.withOpacity(0.25), width: 1.5),
                ),
                child: Text(
                  'Analysis completed but unable to calculate specific score. This is a neutral rating.',
                  style: TextStyle(color: Colors.white, fontSize: 14, height: 1.5),
                  textAlign: TextAlign.center,
                ),
              ),
            ]),
          ),
        );
      }
      
      final scoreValue = double.tryParse(dealRating.toString()) ?? 5.0;
      final double scorePercent = ((scoreValue / 10.0).clamp(0.0, 1.0)).toDouble();
      
      return Card(
        margin: EdgeInsets.symmetric(vertical: 12),
        elevation: 8,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(24)),
        child: Container(
          padding: EdgeInsets.all(24),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(24),
            gradient: LinearGradient(
              begin: Alignment.topLeft,
              end: Alignment.bottomRight,
              colors: [
                _getRatingColor(dealRating).withOpacity(0.85),
                _getRatingColor(dealRating),
              ],
            ),
            boxShadow: [
              BoxShadow(
                color: _getRatingColor(dealRating).withOpacity(0.3),
                blurRadius: 16,
                offset: Offset(0, 8),
              )
            ],
          ),
          child: Column(children: [
            Text('Deal Fairness Score', style: TextStyle(color: Colors.white70, fontSize: 16, fontWeight: FontWeight.w500)),
            SizedBox(height: 16),
            Stack(alignment: Alignment.center, children: [
              Container(
                width: 120,
                height: 120,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: Colors.white.withOpacity(0.15),
                  border: Border.all(color: Colors.white.withOpacity(0.4), width: 3),
                ),
              ),
              SizedBox(
                width: 120,
                height: 120,
                child: CircularProgressIndicator(
                  value: scorePercent,
                  strokeWidth: 8,
                  valueColor: AlwaysStoppedAnimation<Color>(Colors.white),
                  backgroundColor: Colors.white.withOpacity(0.2),
                ),
              ),
              Column(mainAxisAlignment: MainAxisAlignment.center, children: [
                Text(
                  scoreValue.toStringAsFixed(1),
                  style: TextStyle(
                    fontSize: 44,
                    fontWeight: FontWeight.bold,
                    color: Colors.white,
                  ),
                ),
                Text('/10', style: TextStyle(color: Colors.white70, fontSize: 14)),
              ]),
            ]),
            SizedBox(height: 20),
            if (finalSummary != null) ...[
              Container(
                padding: EdgeInsets.all(14),
                decoration: BoxDecoration(
                  color: Colors.white.withOpacity(0.15),
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(color: Colors.white.withOpacity(0.25), width: 1.5),
                ),
                child: Text(
                  finalSummary.toString(),
                  style: TextStyle(color: Colors.white, fontSize: 14, height: 1.5),
                  textAlign: TextAlign.center,
                ),
              ),
            ],
          ]),
        ),
      );
    }

    // Build red flags section
    Widget _buildRedFlags() {
      if (fairnessAnalysis.containsKey('error') || fairnessAnalysis.isEmpty) return SizedBox.shrink();
      
      final redFlags = fairnessAnalysis['red_flags'] ?? fairnessAnalysis['RedFlags'] ?? fairnessAnalysis['redFlags'];
      if (redFlags == null || (redFlags as List).isEmpty) return SizedBox.shrink();
      
      return _sectionCard('⚠️ Red Flags - Watch Out!', Icons.error_outline, Colors.red[700]!, [
        ...(redFlags as List).map<Widget>((flag) {
          final issue = flag['issue'] ?? flag['Issue'] ?? flag.toString();
          final severity = flag['severity'] ?? flag['Severity'] ?? 'Medium';
          final why = flag['why'] ?? flag['Why'] ?? flag['clause'] ?? '';
          
          Color severityColor;
          IconData severityIcon;
          switch (severity.toString().toLowerCase()) {
            case 'high':
              severityColor = Colors.red[700]!;
              severityIcon = Icons.dangerous;
              break;
            case 'medium':
              severityColor = Colors.orange[700]!;
              severityIcon = Icons.warning_amber;
              break;
            default:
              severityColor = Colors.yellow[700]!;
              severityIcon = Icons.info;
          }
          
          return Container(
            margin: EdgeInsets.only(bottom: 12),
            padding: EdgeInsets.all(14),
            decoration: BoxDecoration(
              color: severityColor.withOpacity(0.08),
              borderRadius: BorderRadius.circular(14),
              border: Border.all(color: severityColor.withOpacity(0.3), width: 2),
              boxShadow: [
                BoxShadow(color: severityColor.withOpacity(0.1), blurRadius: 8, offset: Offset(0, 2))
              ],
            ),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Container(
                  padding: EdgeInsets.all(6),
                  decoration: BoxDecoration(color: severityColor, borderRadius: BorderRadius.circular(8)),
                  child: Icon(severityIcon, color: Colors.white, size: 18),
                ),
                SizedBox(width: 10),
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(
                      issue.toString(),
                      style: TextStyle(fontWeight: FontWeight.w700, color: Colors.red[900], fontSize: 14),
                    ),
                    Text(
                      severity.toString().toUpperCase(),
                      style: TextStyle(color: severityColor, fontSize: 11, fontWeight: FontWeight.bold, letterSpacing: 0.5),
                    ),
                  ]),
                ),
              ]),
              if (why.toString().isNotEmpty) ...[
                SizedBox(height: 10),
                Container(
                  padding: EdgeInsets.all(10),
                  decoration: BoxDecoration(color: Colors.white.withOpacity(0.6), borderRadius: BorderRadius.circular(8)),
                  child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Icon(Icons.lightbulb_outline, color: Colors.orange[700], size: 16),
                    SizedBox(width: 8),
                    Expanded(child: Text(why.toString(), style: TextStyle(color: Colors.grey[800], fontSize: 12, height: 1.4))),
                  ]),
                ),
              ],
            ]),
          );
        }),
      ]);
    }

    // Build green flags section
    Widget _buildGreenFlags() {
      if (fairnessAnalysis.containsKey('error') || fairnessAnalysis.isEmpty) return SizedBox.shrink();
      
      final greenFlags = fairnessAnalysis['green_flags'] ?? fairnessAnalysis['GreenFlags'] ?? fairnessAnalysis['greenFlags'];
      if (greenFlags == null || (greenFlags as List).isEmpty) return SizedBox.shrink();
      
      return _sectionCard('✅ Green Flags - Great Terms!', Icons.thumb_up_outlined, Colors.green[700]!, [
        ...(greenFlags as List).map<Widget>((flag) {
          final benefit = flag['benefit'] ?? flag['Benefit'] ?? flag.toString();
          final value = flag['value'] ?? flag['Value'] ?? '';
          
          return Container(
            margin: EdgeInsets.only(bottom: 12),
            padding: EdgeInsets.all(14),
            decoration: BoxDecoration(
              color: Colors.green[50],
              borderRadius: BorderRadius.circular(14),
              border: Border.all(color: Colors.green[300]!, width: 2),
              boxShadow: [
                BoxShadow(color: Colors.green[300]!.withOpacity(0.2), blurRadius: 8, offset: Offset(0, 2))
              ],
            ),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Container(
                padding: EdgeInsets.all(8),
                decoration: BoxDecoration(color: Colors.green[700], shape: BoxShape.circle),
                child: Icon(Icons.check, color: Colors.white, size: 18),
              ),
              SizedBox(width: 12),
              Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(benefit.toString(), style: TextStyle(fontWeight: FontWeight.bold, color: Colors.green[900], fontSize: 14)),
                if (value.toString().isNotEmpty) ...[
                  SizedBox(height: 4),
                  Container(
                    padding: EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                    decoration: BoxDecoration(color: Colors.green[100], borderRadius: BorderRadius.circular(6)),
                    child: Text(value.toString(), style: TextStyle(color: Colors.green[800], fontSize: 12, fontWeight: FontWeight.w600)),
                  ),
                ],
              ])),
            ]),
          );
        }),
      ]);
    }

    // Build negotiable items section
    Widget _buildNegotiableItems() {
      final negotiableItems = negotiationAdvice['negotiable_items'] ?? negotiationAdvice['negotiableItems'] ?? [];
      if (negotiableItems == null || (negotiableItems as List).isEmpty) return SizedBox.shrink();
      
      return _sectionCard('💰 Negotiable Items', Icons.monetization_on, Colors.amber[700]!, [
        ...(negotiableItems as List).map<Widget>((item) {
          final itemName = item['item'] ?? item['Item'] ?? '';
          final tips = item['tips'] ?? item['Tips'] ?? '';
          final example = item['example'] ?? item['Example'] ?? '';
          
          return Container(
            margin: EdgeInsets.only(bottom: 16),
            padding: EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: Colors.amber[50],
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: Colors.amber[200]!),
            ),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Icon(Icons.swap_horiz, color: Colors.amber[700], size: 20),
                SizedBox(width: 8),
                Expanded(child: Text(itemName.toString(), style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16, color: Colors.amber[900]))),
              ]),
              if (tips.toString().isNotEmpty) ...[
                SizedBox(height: 8),
                Text(tips.toString(), style: TextStyle(color: Colors.grey[700], fontSize: 13)),
              ],
              if (example.toString().isNotEmpty) ...[
                SizedBox(height: 8),
                Container(
                  padding: EdgeInsets.all(8),
                  decoration: BoxDecoration(
                    color: Colors.white,
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Icon(Icons.format_quote, color: Colors.amber[700], size: 16),
                    SizedBox(width: 4),
                    Expanded(child: Text('"$example"', style: TextStyle(fontStyle: FontStyle.italic, color: Colors.grey[800], fontSize: 12))),
                  ]),
                ),
              ],
            ]),
          );
        }),
      ]);
    }

    // Build vehicle info card with icon
    Widget _buildVehicleCard() {
      return _sectionCard('🚗 Vehicle Information', Icons.directions_car, Colors.blue[700]!, [
        _infoRow('Make', fullExtraction['make'], prefixIcon: Icons.business),
        _infoRow('Model', fullExtraction['model'], prefixIcon: Icons.directions_car),
        _infoRow('Year', fullExtraction['year'], prefixIcon: Icons.calendar_today),
        _infoRow('Color', fullExtraction['color'], prefixIcon: Icons.palette),
        _infoRow('VIN', fullExtraction['vin'], prefixIcon: Icons.qr_code),
        _infoRow('License Plate', fullExtraction['license_plate'], prefixIcon: Icons.confirmation_number),
      ]);
    }

    // Build financial terms card
    Widget _buildFinancialCard() {
      return _sectionCard('💵 Lease Financial Terms', Icons.attach_money, Colors.green[700]!, [
        _infoRow(
          'Monthly Payment',
          fullExtraction['monthly_payment'] != null ? '\$${fullExtraction['monthly_payment']}' : null,
          valueColor: Colors.green[700],
          prefixIcon: Icons.payment,
        ),
        _infoRow(
          'Security Deposit',
          fullExtraction['security_deposit'] != null ? '\$${fullExtraction['security_deposit']}' : null,
          prefixIcon: Icons.savings,
        ),
        _infoRow('Late Fee', fullExtraction['late_fee'], prefixIcon: Icons.warning),
      ]);
    }

    // Build duration & mileage card
    Widget _buildDurationCard() {
      return _sectionCard('📅 Lease Duration & Mileage', Icons.schedule, Colors.purple[700]!, [
        _infoRow('Term (months)', fullExtraction['lease_term_months'], prefixIcon: Icons.timelapse),
        _infoRow('Mileage/Year', fullExtraction['mileage_allowance_per_year'], prefixIcon: Icons.speed),
        _infoRow('Excess Rate', fullExtraction['excess_mileage_rate'], prefixIcon: Icons.trending_up),
      ]);
    }

    // Build parties card
    Widget _buildPartiesCard() {
      return _sectionCard('👥 Lease Parties', Icons.people, Colors.indigo[700]!, [
        _sectionCard('Lessor (Lessor)', Icons.business_center, Colors.indigo[400]!, [
          _infoRow('Name', fullExtraction['lessor_name'], prefixIcon: Icons.person),
          _infoRow('Email', fullExtraction['lessor_email'], prefixIcon: Icons.email),
          _infoRow('Phone', fullExtraction['lessor_phone'], prefixIcon: Icons.phone),
          _infoRow('Address', fullExtraction['lessor_address'], prefixIcon: Icons.location_on),
        ]),
        _sectionCard('Lessee (Renter)', Icons.person, Colors.indigo[400]!, [
          _infoRow('Name', fullExtraction['lessee_name'], prefixIcon: Icons.person),
          _infoRow('Email', fullExtraction['lessee_email'], prefixIcon: Icons.email),
          _infoRow('Phone', fullExtraction['lessee_phone'], prefixIcon: Icons.phone),
          _infoRow('Address', fullExtraction['lessee_address'], prefixIcon: Icons.location_on),
        ]),
      ]);
    }

    // Build NHTSA decoded data card
    Widget _buildNHTSACard() {
      if (fullExtraction['decoded'] == null) return SizedBox.shrink();
      return _sectionCard('🔍 NHTSA Vehicle Decode', Icons.search, Colors.teal[700]!, [
        _infoRow('Manufacturer', fullExtraction['decoded']?['Manufacturer'], prefixIcon: Icons.factory),
        _infoRow('Body Class', fullExtraction['decoded']?['BodyClass'], prefixIcon: Icons.car_rental),
        _infoRow('Engine Model', fullExtraction['decoded']?['EngineModel'], prefixIcon: Icons.settings),
      ]);
    }

    // Build recalls card
    Widget _buildRecallsCard() {
      if (fullExtraction['recalls'] == null || (fullExtraction['recalls'] as List).isEmpty) return SizedBox.shrink();
      return _sectionCard('⚠️ Vehicle Recalls', Icons.report_problem, Colors.red[700]!, [
        ...(fullExtraction['recalls'] as List).map<Widget>((recall) => Container(
          margin: EdgeInsets.only(bottom: 8),
          padding: EdgeInsets.all(10),
          decoration: BoxDecoration(
            color: Colors.red[50],
            borderRadius: BorderRadius.circular(8),
          ),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Icon(Icons.warning, color: Colors.red[700], size: 18),
            SizedBox(width: 8),
            Expanded(child: Text(recall.toString(), style: TextStyle(color: Colors.red[900], fontSize: 13))),
          ]),
        )),
      ]);
    }

    return SingleChildScrollView(
      child: Padding(
        padding: const EdgeInsets.all(12.0),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          if (_jobPolling)
            Card(
              color: Colors.amber[50],
              elevation: 4,
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
              child: Padding(
                padding: const EdgeInsets.all(16.0),
                child: Row(children: [
                  SizedBox(width: 24, height: 24, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.amber[700])),
                  SizedBox(width: 16),
                  Expanded(child: Text('Extraction taking place...', style: TextStyle(color: Colors.amber[900], fontWeight: FontWeight.w500))),
                ]),
              ),
            ),
          Row(mainAxisAlignment: MainAxisAlignment.end, children: [
            IconButton(
              icon: Icon(Icons.exit_to_app, color: Colors.grey[600]),
              tooltip: 'Logout',
              onPressed: () async {
                setState(() => _loading = true);
                try {
                  await http.post(
                    Uri.parse('$_apiBase/logout'),
                    headers: {
                      if (_globalJwtToken != null && _globalJwtToken!.isNotEmpty)
                        'Authorization': 'Bearer $_globalJwtToken',
                    },
                  );
                } catch (e) {
                  // ignore network/logout errors
                } finally {
                  setState(() => _loading = false);
                }
                Navigator.of(context).pushAndRemoveUntil(MaterialPageRoute(builder: (_) => AppRoot()), (r) => false);
              },
            ),
            IconButton(
              icon: Icon(Icons.copy_all, color: Colors.grey[600]),
              tooltip: 'Copy raw JSON',
              onPressed: () {
                Clipboard.setData(ClipboardData(text: jsonEncode(_result))).then((_) {
                  ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('JSON copied to clipboard')));
                });
              },
            ),
            Row(children: [
              Text('Raw', style: TextStyle(color: Colors.grey[600], fontSize: 12)),
              Switch(
                value: _showRaw,
                onChanged: (v) => _safeSetState(() => _showRaw = v),
                activeColor: Colors.indigo,
              ),
            ])
          ]),

          if (_showRaw) _sectionCard('📄 Raw JSON', Icons.code, Colors.grey[700]!, [
            SelectableText(JsonEncoder.withIndent('  ').convert(_result), style: TextStyle(fontSize: 12, fontFamily: 'monospace')),
          ]) else ...[
            // Deal Score Card
            _buildDealScoreCard(),
            
            // Red Flags
            _buildRedFlags(),
            
            // Green Flags  
            _buildGreenFlags(),
            
            // Negotiable Items
            _buildNegotiableItems(),
            
            // Vehicle Information
            _buildVehicleCard(),
            
            // Financial Terms
            _buildFinancialCard(),
            
            // Duration & Mileage
            _buildDurationCard(),
            
            // Parties
            _buildPartiesCard(),
            
            // NHTSA Decode
            _buildNHTSACard(),
            
            // Recalls
            _buildRecallsCard(),
            
            SizedBox(height: 20),
          ]
        ]),
      ),
    );
  }

  Widget _buildChatView() {
    final contractForChat = _selectedContractForChat ?? _result;
    final contractName = contractForChat?['saved_name'] ?? 
                        (contractForChat != null ? 'Current Contract' : 'No Contract Selected');

    return Column(
      children: [
        if (contractForChat != null) ...[
          Container(
            padding: EdgeInsets.all(8),
            color: Colors.blue[50],
            child: Row(
              children: [
                Icon(Icons.chat, color: Colors.blue[700]),
                SizedBox(width: 8),
                Text(
                  'Chatting about: $contractName',
                  style: TextStyle(fontWeight: FontWeight.w500, color: Colors.blue[700]),
                ),
                Spacer(),
                TextButton(
                  onPressed: () => _tabController.animateTo(1), // Switch to Contracts tab
                  child: Text('Change Contract'),
                ),
              ],
            ),
          ),
        ],
        Expanded(
          child: _chatMessages.isEmpty
              ? Center(child: Text(contractForChat == null 
                  ? 'Select a contract from the Contracts tab to start chatting!' 
                  : 'Upload a lease PDF, then ask about negotiation strategies!'))
              : ListView.builder(
                  itemCount: _chatMessages.length,
                  itemBuilder: (context, index) {
                    final msg = _chatMessages[index];
                    final isBot = msg['role'] == 'bot';
                    return Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 12.0, vertical: 8.0),
                      child: Align(
                        alignment: isBot ? Alignment.centerLeft : Alignment.centerRight,
                        child: Container(
                          constraints: BoxConstraints(maxWidth: 300),
                          padding: EdgeInsets.all(12),
                          decoration: BoxDecoration(
                            color: isBot ? Colors.grey[200] : Colors.blue[100],
                            borderRadius: BorderRadius.circular(12),
                          ),
                          child: SelectableText(msg['text'] ?? '', style: TextStyle(color: Colors.grey[900])),
                        ),
                      ),
                    );
                  },
                ),
        ),

        Container(
          padding: EdgeInsets.all(12),
          decoration: BoxDecoration(border: Border(top: BorderSide(color: Colors.grey[300]!))),
          child: Row(
            children: [
              Expanded(
                child: TextField(
                  controller: _chatInputController,
                  enabled: !_chatLoading,
                  decoration: InputDecoration(
                    hintText: 'Ask about your lease...',
                    border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
                    contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                  ),
                  onSubmitted: (_) => _sendChatMessage(),
                ),
              ),
              SizedBox(width: 8),
              IconButton(
                onPressed: _chatLoading ? null : _sendChatMessage,
                icon: Icon(_chatLoading ? Icons.hourglass_bottom : Icons.send),
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _buildContractsView() {
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.all(12.0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                children: [
                  Expanded(
                    child: ElevatedButton.icon(
                      onPressed: _saveCurrentContract,
                      icon: Icon(Icons.save),
                      label: Text('Save Contract'),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: Colors.green,
                        foregroundColor: Colors.white,
                      ),
                    ),
                  ),
                  SizedBox(width: 12),
                  Expanded(
                    child: ElevatedButton.icon(
                      onPressed: _storedContracts.length >= 2 ? () {
                        _safeSetState(() {
                          _comparisonMode = !_comparisonMode;
                          _selectedContractsForComparison.clear();
                        });
                      } : null,
                      icon: Icon(_comparisonMode ? Icons.cancel : Icons.compare),
                      label: Text(_comparisonMode ? 'Cancel Compare' : 'Compare'),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: _comparisonMode ? Colors.grey : Colors.blue,
                        foregroundColor: Colors.white,
                      ),
                    ),
                  ),
                ],
              ),
              if (_comparisonMode && _selectedContractsForComparison.length >= 2)
                Padding(
                  padding: const EdgeInsets.only(top: 12.0),
                  child: ElevatedButton.icon(
                    onPressed: () => _showComparisonDialog(),
                    icon: Icon(Icons.visibility),
                    label: Text('View Comparison'),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.purple,
                      foregroundColor: Colors.white,
                    ),
                  ),
                ),
              SizedBox(height: 16),
              Text(
                'Stored Contracts (${_storedContracts.length})',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
              ),
              if (_comparisonMode)
                Text(
                  'Select 2 or more contracts to compare',
                  style: TextStyle(fontSize: 14, color: Colors.grey[600]),
                ),
            ],
          ),
        ),
        Expanded(
          child: _storedContracts.isEmpty
              ? Center(child: Text('No saved contracts. Upload and save contracts to compare them.'))
              : ListView.builder(
                  itemCount: _storedContracts.length,
                  itemBuilder: (context, index) {
                    final contract = _storedContracts[index];
                    final fullExtraction = convertToTypedMap((contract['full_extraction'] ?? {})) as Map<String, dynamic>;
                    final fairnessAnalysis = convertToTypedMap((contract['fairness_analysis'] ?? {})) as Map<String, dynamic>;
                    final dealRating = fairnessAnalysis['deal_rating'] ?? fairnessAnalysis['DealRating'] ?? fairnessAnalysis['dealRating'] ?? fairnessAnalysis['fairness_score'];
                    final contractName = contract['saved_name'] ?? 'Contract ${index + 1}';

                    return Card(
                      margin: EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                      elevation: 4,
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                      child: Padding(
                        padding: const EdgeInsets.all(16.0),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              children: [
                                if (_comparisonMode) ...[
                                  Checkbox(
                                    value: _selectedContractsForComparison.contains(contract),
                                    onChanged: (bool? value) {
                                      _safeSetState(() {
                                        if (value == true) {
                                          _selectedContractsForComparison.add(contract);
                                        } else {
                                          _selectedContractsForComparison.remove(contract);
                                        }
                                      });
                                    },
                                  ),
                                  SizedBox(width: 8),
                                ],
                                Expanded(
                                  child: Text(
                                    contractName,
                                    style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
                                  ),
                                ),
                                if (dealRating != null) ...[
                                  Container(
                                    padding: EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                                    decoration: BoxDecoration(
                                      color: _getRatingColor(dealRating).withOpacity(0.1),
                                      borderRadius: BorderRadius.circular(12),
                                      border: Border.all(color: _getRatingColor(dealRating), width: 1),
                                    ),
                                    child: Row(
                                      children: [
                                        Icon(_getRatingIcon(dealRating), size: 16, color: _getRatingColor(dealRating)),
                                        SizedBox(width: 4),
                                        Text(
                                          dealRating.toString(),
                                          style: TextStyle(
                                            color: _getRatingColor(dealRating),
                                            fontWeight: FontWeight.bold,
                                          ),
                                        ),
                                      ],
                                    ),
                                  ),
                                ],
                              ],
                            ),
                            SizedBox(height: 8),
                            Text(
                              '${fullExtraction['make'] ?? 'Unknown'} ${fullExtraction['model'] ?? 'Model'} (${fullExtraction['year'] ?? 'Year'})',
                              style: TextStyle(color: Colors.grey[600]),
                            ),
                            if (fullExtraction['monthly_payment'] != null) ...[
                              SizedBox(height: 4),
                              Text(
                                'Monthly: \$${fullExtraction['monthly_payment']}',
                                style: TextStyle(fontWeight: FontWeight.w500, color: Colors.green[700]),
                              ),
                            ],
                            SizedBox(height: 12),
                            Row(
                              children: [
                                Expanded(
                                  child: ElevatedButton.icon(
                                    onPressed: () {
                                      _safeSetState(() {
                                        _result = contract;
                                        _tabController.animateTo(0); // Switch to Analysis tab
                                      });
                                    },
                                    icon: Icon(Icons.visibility),
                                    label: Text('View'),
                                    style: ElevatedButton.styleFrom(
                                      backgroundColor: Colors.blue,
                                      foregroundColor: Colors.white,
                                    ),
                                  ),
                                ),
                                SizedBox(width: 8),
                                Expanded(
                                  child: ElevatedButton.icon(
                                    onPressed: () {
                                      _safeSetState(() {
                                        _selectedContractForChat = contract;
                                        _chatMessages.clear(); // Clear chat when switching contracts
                                        _tabController.animateTo(2); // Switch to Chat tab
                                      });
                                    },
                                    icon: Icon(Icons.chat),
                                    label: Text('Chat'),
                                    style: ElevatedButton.styleFrom(
                                      backgroundColor: Colors.purple,
                                      foregroundColor: Colors.white,
                                    ),
                                  ),
                                ),
                                SizedBox(width: 8),
                                IconButton(
                                  onPressed: () {
                                    showDialog(
                                      context: context,
                                      builder: (context) => AlertDialog(
                                        title: Text('Delete Contract'),
                                        content: Text('Are you sure you want to delete "$contractName"?'),
                                        actions: [
                                          TextButton(
                                            onPressed: () => Navigator.of(context).pop(),
                                            child: Text('Cancel'),
                                          ),
                                          TextButton(
                                            onPressed: () {
                                              _safeSetState(() {
                                                _storedContracts.removeAt(index);
                                              });
                                              Navigator.of(context).pop();
                                            },
                                            child: Text('Delete', style: TextStyle(color: Colors.red)),
                                          ),
                                        ],
                                      ),
                                    );
                                  },
                                  icon: Icon(Icons.delete, color: Colors.red),
                                  tooltip: 'Delete',
                                ),
                              ],
                            ),
                          ],
                        ),
                      ),
                    );
                  },
                ),
        ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text('Car Lease Assistant 🔧'),
        actions: [
          IconButton(
            icon: Icon(Icons.exit_to_app),
            tooltip: 'Logout',
            onPressed: () async {
              setState(() => _loading = true);
              try {
                await http.post(
                  Uri.parse('$_apiBase/logout'),
                  headers: {
                    if (_globalJwtToken != null && _globalJwtToken!.isNotEmpty)
                      'Authorization': 'Bearer $_globalJwtToken',
                  },
                );
              } catch (e) {}
              setState(() => _loading = false);
              Navigator.of(context).pushAndRemoveUntil(MaterialPageRoute(builder: (_) => AppRoot()), (r) => false);
            },
          ),
        ],
        bottom: TabBar(
          controller: _tabController,
          tabs: [
            Tab(icon: Icon(Icons.description), text: 'Analysis'),
            Tab(icon: Icon(Icons.folder), text: 'Contracts'),
            Tab(icon: Icon(Icons.chat), text: 'Chat'),
          ],
        ),
      ),
      body: TabBarView(
        controller: _tabController,
        children: [
          // Analysis Tab
          Column(
            children: [
              Padding(
                padding: const EdgeInsets.all(12.0),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Row(children: [
                      ElevatedButton.icon(
                        onPressed: _loading ? null : _pickAndUploadPdf,
                        icon: Icon(Icons.upload_file),
                        label: Text(_loading ? 'Extraction taking place...' : 'Upload Lease PDF'),
                      ),
                      SizedBox(width: 12),
                      ElevatedButton.icon(
                        onPressed: _saveCurrentContract,
                        icon: Icon(Icons.save),
                        label: Text('Save Contract'),
                        style: ElevatedButton.styleFrom(
                          backgroundColor: Colors.green,
                          foregroundColor: Colors.white,
                        ),
                      ),
                      SizedBox(width: 12),
                      ElevatedButton.icon(
                        onPressed: _testConnection,
                        icon: Icon(Icons.wifi_tethering),
                        label: Text('Test Connection'),
                      ),
                    ]),
                    SizedBox(height: 10),
                    Row(children: [
                      Expanded(child: Text('Fast Mode (skip vehicle decode, keep LLM)', style: TextStyle(fontWeight: FontWeight.w600))),
                      Switch(value: _fastMode, onChanged: (v) => _safeSetState(() => _fastMode = v)),
                    ]),
                    SizedBox(height: 8),
                    Row(children: [
                      Expanded(child: Text('API: $_apiBase', style: TextStyle(fontWeight: FontWeight.bold))),
                      Text('Platform: ${kIsWeb ? 'Web' : Platform.operatingSystem}', style: TextStyle(color: Colors.grey[700])),
                    ])
                  ],
                ),
              ),
              Expanded(child: _buildAnalysisView()),
            ],
          ),

          // Contracts Tab
          _buildContractsView(),

          // Chat Tab
          _buildChatView(),
        ],
      ),
    );
  }
}
