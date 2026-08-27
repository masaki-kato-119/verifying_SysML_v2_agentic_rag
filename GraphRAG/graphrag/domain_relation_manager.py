"""
プラグイン式ドメイン拡張アーキテクチャ
汎用関係とドメイン特化関係を管理する機能
"""
from typing import Dict, List, Optional


class UniversalRelationManager:
    """
    汎用関係マネージャー
    
    すべてのドメインで使用可能な基本的な関係を管理
    """
    
    UNIVERSAL_RELATIONS: Dict[str, List[str]] = {
        'is-a': ['is', 'type', 'kind', 'instance-of', 'is a', 'is an'],
        'part-of': ['contains', 'includes', 'composed-of', 'member-of', 'part of'],
        'uses': ['utilizes', 'employs', 'applies', 'leverages', 'use'],
        'depends-on': ['requires', 'needs', 'relies-on', 'based-on', 'depends on'],
        'related-to': ['associated-with', 'connected-to', 'linked-to', 'related to'],
        'defines': ['specifies', 'describes', 'declares', 'define'],
        'implements': ['realizes', 'provides', 'fulfills', 'implement']
    }
    
    def __init__(self):
        """汎用関係マネージャーを初期化"""
        pass
    
    def get_relations(self) -> Dict[str, List[str]]:
        """
        汎用関係を取得
        
        Returns:
            Dict[str, List[str]]: 関係タイプ -> 関係語彙のリスト
        """
        # dict.copy()は浅いコピーで内側のlistが共有されてしまうため、
        # 呼び出し側がリストを変更するとクラス変数を汚染する。リストも複製する。
        return {relation_type: list(vocab) for relation_type, vocab in self.UNIVERSAL_RELATIONS.items()}
    
    def get_relation_type(self, vocabulary: str) -> Optional[str]:
        """
        関係語彙から関係タイプを取得
        
        Args:
            vocabulary: 関係語彙
        
        Returns:
            Optional[str]: 関係タイプ（見つからない場合はNone）
        """
        vocabulary_lower = vocabulary.lower().strip()
        
        # 完全一致を優先
        for relation_type, vocabularies in self.UNIVERSAL_RELATIONS.items():
            for vocab in vocabularies:
                vocab_lower = vocab.lower().strip()
                if vocabulary_lower == vocab_lower:
                    return relation_type
        
        # 部分一致
        for relation_type, vocabularies in self.UNIVERSAL_RELATIONS.items():
            for vocab in vocabularies:
                vocab_lower = vocab.lower().strip()
                if vocabulary_lower in vocab_lower or vocab_lower in vocabulary_lower:
                    return relation_type
        
        return None


class DomainRelationManager:
    """
    ドメイン関係マネージャー
    
    汎用関係 + ドメイン特化関係を統合管理
    """
    
    DOMAIN_RELATIONS: Dict[str, Dict[str, List[str]]] = {
        'sysml_v2': {
            'has_parameter': ['parameter', 'param', 'argument', 'has parameter'],
            'requires_input': ['input', 'requires', 'needs', 'requires input'],
            'produces_output': ['output', 'produces', 'generates', 'produces output'],
            'is_defined_in': ['defined in', 'specified in', 'described in', 'is defined in'],
            'governs_flow_of': ['controls', 'governs', 'manages', 'governs flow of'],
            'splits_into': ['splits', 'divides', 'branches', 'splits into'],
            'merges_from': ['merges', 'combines', 'joins', 'merges from'],
            'specializes': ['extends', 'inherits', 'derives', 'specialize'],
            'subsets': ['restricts', 'narrows', 'limits', 'subset'],
            'redefines': ['overrides', 'replaces', 'modifies', 'redefine'],
            'types': ['types', 'typing', 'type'],
            'membership': ['membership', 'member'],
            'ownership': ['ownership', 'owns', 'own']
        },
        'software_architecture': {
            'implements': ['realizes', 'provides', 'implement'],
            'calls': ['invokes', 'executes', 'call'],
            'inherits_from': ['extends', 'derives_from', 'inherits from'],
            'aggregates': ['composes', 'contains', 'aggregate'],
            'depends_on': ['requires', 'uses', 'depends on']
        },
        'business_process': {
            'triggers': ['initiates', 'starts', 'trigger'],
            'approves': ['validates', 'confirms', 'approve'],
            'escalates_to': ['forwards_to', 'delegates_to', 'escalates to'],
            'precedes': ['comes_before', 'leads_to', 'precede'],
            'follows': ['comes_after', 'succeeds', 'follow']
        }
    }
    
    def __init__(self, domain: str = 'universal'):
        """
        ドメイン関係マネージャーを初期化
        
        Args:
            domain: アクティブなドメイン（'universal', 'sysml_v2', 'software_architecture', 'business_process'）
        """
        self.universal_manager = UniversalRelationManager()
        self.active_domain = domain
        self.custom_relations: Dict[str, List[str]] = {}
    
    def get_all_relations(self) -> Dict[str, List[str]]:
        """
        汎用関係 + ドメイン特化関係を統合
        
        Returns:
            Dict[str, List[str]]: 関係タイプ -> 関係語彙のリスト
        """
        combined = self.universal_manager.get_relations()

        if self.active_domain in self.DOMAIN_RELATIONS:
            combined.update(self.get_domain_relations())

        combined.update({relation_type: list(vocab) for relation_type, vocab in self.custom_relations.items()})
        
        return combined
    
    def switch_domain(self, domain: str):
        """
        ドメインを動的に切り替え
        
        Args:
            domain: 切り替え先のドメイン
        """
        if domain in self.DOMAIN_RELATIONS or domain == 'universal':
            self.active_domain = domain
        else:
            raise ValueError(f"Unknown domain: {domain}")
    
    def add_custom_relations(self, custom_relations: Dict[str, List[str]]):
        """
        カスタム関係を追加
        
        Args:
            custom_relations: カスタム関係の辞書（関係タイプ -> 関係語彙のリスト）
        """
        self.custom_relations.update(custom_relations)
    
    def remove_custom_relations(self, relation_types: List[str]):
        """
        カスタム関係を削除
        
        Args:
            relation_types: 削除する関係タイプのリスト
        """
        for relation_type in relation_types:
            if relation_type in self.custom_relations:
                del self.custom_relations[relation_type]
    
    def get_relation_type(self, vocabulary: str) -> Optional[str]:
        """
        関係語彙から関係タイプを取得
        
        Args:
            vocabulary: 関係語彙
        
        Returns:
            Optional[str]: 関係タイプ（見つからない場合はNone）
        """
        vocabulary_lower = vocabulary.lower().strip()
        
        # まず汎用関係で検索
        relation_type = self.universal_manager.get_relation_type(vocabulary)
        if relation_type:
            return relation_type
        
        # 次にドメイン特化関係で検索
        if self.active_domain in self.DOMAIN_RELATIONS:
            # 関係タイプ名そのものと一致する場合
            if vocabulary_lower in self.DOMAIN_RELATIONS[self.active_domain]:
                return vocabulary_lower
            
            # 完全一致を優先
            for relation_type, vocabularies in self.DOMAIN_RELATIONS[self.active_domain].items():
                for vocab in vocabularies:
                    vocab_lower = vocab.lower().strip()
                    if vocabulary_lower == vocab_lower:
                        return relation_type
            
            # 部分一致
            for relation_type, vocabularies in self.DOMAIN_RELATIONS[self.active_domain].items():
                for vocab in vocabularies:
                    vocab_lower = vocab.lower().strip()
                    if vocabulary_lower in vocab_lower or vocab_lower in vocabulary_lower:
                        return relation_type
        
        # 最後にカスタム関係で検索
        # 完全一致を優先
        for relation_type, vocabularies in self.custom_relations.items():
            for vocab in vocabularies:
                vocab_lower = vocab.lower().strip()
                if vocabulary_lower == vocab_lower:
                    return relation_type
        
        # 部分一致
        for relation_type, vocabularies in self.custom_relations.items():
            for vocab in vocabularies:
                vocab_lower = vocab.lower().strip()
                if vocabulary_lower in vocab_lower or vocab_lower in vocabulary_lower:
                    return relation_type
        
        return None
    
    def get_domain_relations(self) -> Dict[str, List[str]]:
        """
        現在のドメインの関係を取得
        
        Returns:
            Dict[str, List[str]]: 関係タイプ -> 関係語彙のリスト
        """
        if self.active_domain in self.DOMAIN_RELATIONS:
            # dict.copy()は浅いコピーで内側のlistが共有されるため、リストも複製する。
            return {
                relation_type: list(vocab)
                for relation_type, vocab in self.DOMAIN_RELATIONS[self.active_domain].items()
            }
        return {}
    
    def get_available_domains(self) -> List[str]:
        """
        利用可能なドメインのリストを取得
        
        Returns:
            List[str]: ドメイン名のリスト
        """
        domains = ['universal']
        domains.extend(list(self.DOMAIN_RELATIONS.keys()))
        return domains
