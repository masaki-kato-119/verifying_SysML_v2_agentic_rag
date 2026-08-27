package CommunicationModel {
    part client : Client;
    part server : Server;

    action checkConnection {
        // 接続が成功するまでリトライするループ
        action retryLoop while not isConnected {
            // リクエスト送信メッセージ
            message requestMsg from client.sendRequest to server.receiveRequest;
            
            // サーバー側での判定結果を待機
            accept response : ConnectionResponse via client;

            // 分岐処理：レスポンスの内容に応じて状態を更新
            if response.status == "Success" {
                assign isConnected := true;
            } else {
                // 失敗時はログを記録して継続
                perform logFailure;
            }
        }
    }
}