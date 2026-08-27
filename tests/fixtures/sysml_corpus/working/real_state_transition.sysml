state def AdvancedSwitch {
    // 属性の定義
    attribute powerLevel : ScalarValues::Real;

    entry; then Off;

    state Off;
    
    state On {
        // 状態への入場時(entry)アクション
        entry action setupSystem;
        // 状態内での実行中(do)アクション
        do action performOperation;
        // 状態からの退場時(exit)アクション
        exit action cleanup;
    }

    // ガード条件(if)と効果アクション(do)を含む遷移
    transition first Off 
        accept TurnOn 
        if powerLevel > 0.0      // ガード条件: 電力が0より大きい場合のみ遷移
        do action logStart       // 効果アクション: 遷移中に実行
        then On;

    // OnからOffへ戻る遷移を追加
    transition OnToOff
        first On
        accept TurnOff
        then Off;

    // OnからOffへ戻る遷移を追加
    transition OnToOff_Auto
        first On
        if powerLevel <= 0.0      // ガード条件
        then Off;

}