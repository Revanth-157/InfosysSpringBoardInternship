import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

// Global JWT token storage
String? _globalJwtToken;
const String API_URL = 'http://localhost:5000';

void main() => runApp(DealerApp());

class DealerApp extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Dealer Chat',
      theme: ThemeData(primarySwatch: Colors.blue),
      home: DealerRoot(),
    );
  }
}

class DealerRoot extends StatefulWidget {
  @override
  _DealerRootState createState() => _DealerRootState();
}

class _DealerRootState extends State<DealerRoot> {
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
    return DealerHomePage(username: _username, onLogout: _onLogout);
  }
}

// ============ LOGIN / REGISTER PAGE ============
class LoginPage extends StatefulWidget {
  final Function(String, String) onLogin;

  LoginPage({required this.onLogin});

  @override
  _LoginPageState createState() => _LoginPageState();
}

class _LoginPageState extends State<LoginPage> {
  final _usernameController = TextEditingController();
  final _passwordController = TextEditingController();
  bool _isLogin = true;
  String _errorMessage = '';
  bool _isLoading = false;

  Future<void> _authenticate() async {
    setState(() => _isLoading = true);
    final username = _usernameController.text.trim();
    final password = _passwordController.text.trim();

    if (username.isEmpty || password.isEmpty) {
      setState(() {
        _errorMessage = 'Please fill in all fields';
        _isLoading = false;
      });
      return;
    }

    try {
      final endpoint = _isLogin ? '/login' : '/register';
      final response = await http.post(
        Uri.parse('$API_URL$endpoint'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'username': username, 'password': password}),
      );

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        widget.onLogin(username, data['token']);
      } else {
        final data = jsonDecode(response.body);
        setState(() {
          _errorMessage = data['error'] ?? 'Authentication failed';
          _isLoading = false;
        });
      }
    } catch (e) {
      setState(() {
        _errorMessage = 'Error: $e';
        _isLoading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(_isLogin ? 'Dealer Login' : 'Dealer Register')),
      body: Padding(
        padding: EdgeInsets.all(16),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            TextField(
              controller: _usernameController,
              decoration: InputDecoration(labelText: 'Username'),
            ),
            SizedBox(height: 16),
            TextField(
              controller: _passwordController,
              obscureText: true,
              decoration: InputDecoration(labelText: 'Password'),
            ),
            SizedBox(height: 16),
            if (_errorMessage.isNotEmpty)
              Padding(
                padding: EdgeInsets.only(bottom: 16),
                child: Text(_errorMessage, style: TextStyle(color: Colors.red)),
              ),
            ElevatedButton(
              onPressed: _isLoading ? null : _authenticate,
              child: Text(_isLogin ? 'Login' : 'Register'),
            ),
            SizedBox(height: 16),
            TextButton(
              onPressed: () => setState(() => _isLogin = !_isLogin),
              child: Text(_isLogin ? 'Need to register?' : 'Already have account?'),
            ),
          ],
        ),
      ),
    );
  }
}

// ============ DEALER HOME PAGE ============
class DealerHomePage extends StatefulWidget {
  final String? username;
  final VoidCallback onLogout;

  DealerHomePage({required this.username, required this.onLogout});

  @override
  _DealerHomePageState createState() => _DealerHomePageState();
}

class _DealerHomePageState extends State<DealerHomePage> {
  List<Map<String, dynamic>> _users = [];
  int? _selectedUserId;
  bool _isLoadingUsers = true;

  @override
  void initState() {
    super.initState();
    _loadUsers();
  }

  Future<void> _loadUsers() async {
    try {
      // Dealer should load regular users (lessees) from the backend
      final response = await http.get(
        Uri.parse('$API_URL/users'),
        headers: {'Authorization': 'Bearer $_globalJwtToken'},
      );

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        setState(() {
          _users = List<Map<String, dynamic>>.from(
            (data['users'] as List? ?? [])
                .map((d) => {'id': d['id'], 'username': d['username']}),
          );
          _isLoadingUsers = false;
        });
      }
    } catch (e) {
      print('Error loading users: $e');
      setState(() => _isLoadingUsers = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text('Dealer Chat - ${widget.username}'),
        actions: [
          IconButton(
            icon: Icon(Icons.logout),
            onPressed: () {
              _globalJwtToken = null;
              widget.onLogout();
            },
          ),
        ],
      ),
      body: Row(
        children: [
          // Left panel: List of users
          Container(
            width: 250,
            decoration: BoxDecoration(
              border: Border(right: BorderSide(color: Colors.grey[300]!)),
            ),
            child: _isLoadingUsers
                ? Center(child: CircularProgressIndicator())
                : _users.isEmpty
                    ? Center(child: Text('No users available'))
                    : ListView.builder(
                        itemCount: _users.length,
                        itemBuilder: (context, index) {
                          final user = _users[index];
                          final isSelected = _selectedUserId == user['id'];
                          return ListTile(
                            title: Text(user['username']),
                            selected: isSelected,
                            onTap: () {
                              setState(() => _selectedUserId = user['id']);
                            },
                            tileColor: isSelected ? Colors.blue[100] : null,
                          );
                        },
                      ),
          ),
          // Right panel: Chat with selected user
          Expanded(
            child: _selectedUserId == null
                ? Center(child: Text('Select a user to chat'))
                : ChatPanel(userId: _selectedUserId!),
          ),
        ],
      ),
    );
  }
}

// ============ CHAT PANEL ============
class ChatPanel extends StatefulWidget {
  final int userId;

  ChatPanel({required this.userId});

  @override
  _ChatPanelState createState() => _ChatPanelState();
}

class _ChatPanelState extends State<ChatPanel> {
  final _messageController = TextEditingController();
  final ScrollController _scrollController = ScrollController();
  List<Map<String, dynamic>> _messages = [];
  bool _isLoadingMessages = false;
  Timer? _pollTimer;

  @override
  void initState() {
    super.initState();
    _loadMessages();
    // Start periodic polling to refresh messages automatically (shorter interval helps keep UI responsive)
    _pollTimer = Timer.periodic(Duration(milliseconds: 1500), (_) {
      if (!mounted) return;
      if (!_isLoadingMessages) _loadMessages();
    });
  }

  @override
  void didUpdateWidget(ChatPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.userId != widget.userId) {
      _messageController.clear();
      _messages.clear();
      _loadMessages();
    }
  }

  Future<void> _loadMessages() async {
    if (_isLoadingMessages) return; // prevent overlapping calls
    setState(() => _isLoadingMessages = true);
    try {
      final response = await http.get(
        Uri.parse('$API_URL/messages/${widget.userId}'),
        headers: {'Authorization': 'Bearer $_globalJwtToken'},
      );

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        setState(() {
          _messages = List<Map<String, dynamic>>.from(data['messages'] ?? []);
        });
      }
    } catch (e) {
      print('Error loading messages: $e');
    } finally {
      if (mounted) setState(() => _isLoadingMessages = false);
    }
    
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    _messageController.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  Future<void> _sendMessage() async {
    final content = _messageController.text.trim();
    if (content.isEmpty) return;

    _messageController.clear();

    try {
      final response = await http.post(
        Uri.parse('$API_URL/send-message'),
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer $_globalJwtToken',
        },
        body: jsonEncode({
          'receiver_id': widget.userId,
          'content': content,
        }),
      );

      if (response.statusCode == 200) {
        await _loadMessages(); // Refresh messages and then scroll
      } else if (response.statusCode == 403) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Cannot send: role restriction')),
        );
      } else {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Failed to send message')),
        );
      }
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Error: $e')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        if (_isLoadingMessages) LinearProgressIndicator(minHeight: 3) else SizedBox(height: 3),
        Expanded(
          child: _messages.isEmpty
              ? Center(child: Text(_isLoadingMessages ? 'Loading messages...' : 'No messages yet'))
              : ListView.builder(
                  controller: _scrollController,
                  itemCount: _messages.length,
                  itemBuilder: (context, index) {
                    final msg = _messages[index];
                    final isMine = msg['is_mine'] ?? false;
                    return Align(
                      alignment: isMine ? Alignment.centerRight : Alignment.centerLeft,
                      child: Container(
                        margin: EdgeInsets.symmetric(vertical: 4, horizontal: 8),
                        padding: EdgeInsets.all(12),
                        decoration: BoxDecoration(
                          color: isMine ? Colors.blue[300] : Colors.grey[300],
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: Text(msg['content']),
                      ),
                    );
                  },
                ),
        ),
        // Message input (always visible)
        Padding(
          padding: EdgeInsets.all(8),
          child: Row(
            children: [
              Expanded(
                child: TextField(
                  controller: _messageController,
                  decoration: InputDecoration(
                    hintText: 'Type a message...',
                    border: OutlineInputBorder(),
                  ),
                  onSubmitted: (_) => _sendMessage(),
                ),
              ),
              SizedBox(width: 8),
              IconButton(
                icon: Icon(Icons.send),
                onPressed: _sendMessage,
              ),
            ],
          ),
        ),
      ],
    );
  }

  // helper used after messages update to make newest item visible
  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.jumpTo(_scrollController.position.maxScrollExtent);
      }
    });
  }
}
