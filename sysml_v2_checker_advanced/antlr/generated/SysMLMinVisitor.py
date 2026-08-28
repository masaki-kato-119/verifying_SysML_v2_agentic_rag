# Generated from SysMLMin.g4 by ANTLR 4.13.2
from antlr4 import *
if "." in __name__:
    from .SysMLMinParser import SysMLMinParser
else:
    from SysMLMinParser import SysMLMinParser

# This class defines a complete generic visitor for a parse tree produced by SysMLMinParser.

class SysMLMinVisitor(ParseTreeVisitor):

    # Visit a parse tree produced by SysMLMinParser#model.
    def visitModel(self, ctx:SysMLMinParser.ModelContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#topLevelElement.
    def visitTopLevelElement(self, ctx:SysMLMinParser.TopLevelElementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#packageDef.
    def visitPackageDef(self, ctx:SysMLMinParser.PackageDefContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#packageBodyElement.
    def visitPackageBodyElement(self, ctx:SysMLMinParser.PackageBodyElementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#prefixMetadataAnnotation.
    def visitPrefixMetadataAnnotation(self, ctx:SysMLMinParser.PrefixMetadataAnnotationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#dependencyStmt.
    def visitDependencyStmt(self, ctx:SysMLMinParser.DependencyStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#eventOccurrenceUsageStmt.
    def visitEventOccurrenceUsageStmt(self, ctx:SysMLMinParser.EventOccurrenceUsageStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#exhibitStateUsageStmt.
    def visitExhibitStateUsageStmt(self, ctx:SysMLMinParser.ExhibitStateUsageStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#portionUsageStmt.
    def visitPortionUsageStmt(self, ctx:SysMLMinParser.PortionUsageStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#occurrenceDef.
    def visitOccurrenceDef(self, ctx:SysMLMinParser.OccurrenceDefContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#occurrenceUsage.
    def visitOccurrenceUsage(self, ctx:SysMLMinParser.OccurrenceUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#individualDef.
    def visitIndividualDef(self, ctx:SysMLMinParser.IndividualDefContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#individualUsage.
    def visitIndividualUsage(self, ctx:SysMLMinParser.IndividualUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#interactionDef.
    def visitInteractionDef(self, ctx:SysMLMinParser.InteractionDefContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#interactionBodyElement.
    def visitInteractionBodyElement(self, ctx:SysMLMinParser.InteractionBodyElementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#participantMember.
    def visitParticipantMember(self, ctx:SysMLMinParser.ParticipantMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#fragmentStmt.
    def visitFragmentStmt(self, ctx:SysMLMinParser.FragmentStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#operandBlock.
    def visitOperandBlock(self, ctx:SysMLMinParser.OperandBlockContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#commentStmt.
    def visitCommentStmt(self, ctx:SysMLMinParser.CommentStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#documentationStmt.
    def visitDocumentationStmt(self, ctx:SysMLMinParser.DocumentationStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#textualRepresentationStmt.
    def visitTextualRepresentationStmt(self, ctx:SysMLMinParser.TextualRepresentationStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#bareDocComment.
    def visitBareDocComment(self, ctx:SysMLMinParser.BareDocCommentContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#aliasStmt.
    def visitAliasStmt(self, ctx:SysMLMinParser.AliasStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#caseDef.
    def visitCaseDef(self, ctx:SysMLMinParser.CaseDefContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#caseUsage.
    def visitCaseUsage(self, ctx:SysMLMinParser.CaseUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#analysisCaseDef.
    def visitAnalysisCaseDef(self, ctx:SysMLMinParser.AnalysisCaseDefContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#analysisCaseUsage.
    def visitAnalysisCaseUsage(self, ctx:SysMLMinParser.AnalysisCaseUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#verificationCaseDef.
    def visitVerificationCaseDef(self, ctx:SysMLMinParser.VerificationCaseDefContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#verificationCaseUsage.
    def visitVerificationCaseUsage(self, ctx:SysMLMinParser.VerificationCaseUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#useCaseDef.
    def visitUseCaseDef(self, ctx:SysMLMinParser.UseCaseDefContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#useCaseUsage.
    def visitUseCaseUsage(self, ctx:SysMLMinParser.UseCaseUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#includeUseCaseUsage.
    def visitIncludeUseCaseUsage(self, ctx:SysMLMinParser.IncludeUseCaseUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#viewDef.
    def visitViewDef(self, ctx:SysMLMinParser.ViewDefContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#viewUsage.
    def visitViewUsage(self, ctx:SysMLMinParser.ViewUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#viewpointDef.
    def visitViewpointDef(self, ctx:SysMLMinParser.ViewpointDefContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#viewpointUsage.
    def visitViewpointUsage(self, ctx:SysMLMinParser.ViewpointUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#renderingDef.
    def visitRenderingDef(self, ctx:SysMLMinParser.RenderingDefContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#renderingUsage.
    def visitRenderingUsage(self, ctx:SysMLMinParser.RenderingUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#metadataDef.
    def visitMetadataDef(self, ctx:SysMLMinParser.MetadataDefContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#metadataUsageKeyword.
    def visitMetadataUsageKeyword(self, ctx:SysMLMinParser.MetadataUsageKeywordContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#metadataUsageShorthand.
    def visitMetadataUsageShorthand(self, ctx:SysMLMinParser.MetadataUsageShorthandContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#calculationDef.
    def visitCalculationDef(self, ctx:SysMLMinParser.CalculationDefContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#constraintDef.
    def visitConstraintDef(self, ctx:SysMLMinParser.ConstraintDefContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#calcBodyElement.
    def visitCalcBodyElement(self, ctx:SysMLMinParser.CalcBodyElementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#resultExpressionMember.
    def visitResultExpressionMember(self, ctx:SysMLMinParser.ResultExpressionMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#calcParameter.
    def visitCalcParameter(self, ctx:SysMLMinParser.CalcParameterContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#assertConstraintUsage.
    def visitAssertConstraintUsage(self, ctx:SysMLMinParser.AssertConstraintUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#calculationUsage.
    def visitCalculationUsage(self, ctx:SysMLMinParser.CalculationUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#constraintUsage.
    def visitConstraintUsage(self, ctx:SysMLMinParser.ConstraintUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#satisfyRequirementUsage.
    def visitSatisfyRequirementUsage(self, ctx:SysMLMinParser.SatisfyRequirementUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#requireUsage.
    def visitRequireUsage(self, ctx:SysMLMinParser.RequireUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#interfaceUsage.
    def visitInterfaceUsage(self, ctx:SysMLMinParser.InterfaceUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#allocationUsage.
    def visitAllocationUsage(self, ctx:SysMLMinParser.AllocationUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#connectionDef.
    def visitConnectionDef(self, ctx:SysMLMinParser.ConnectionDefContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#connectionBodyElement.
    def visitConnectionBodyElement(self, ctx:SysMLMinParser.ConnectionBodyElementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#connectionEndMember.
    def visitConnectionEndMember(self, ctx:SysMLMinParser.ConnectionEndMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#allocationDef.
    def visitAllocationDef(self, ctx:SysMLMinParser.AllocationDefContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#activityDef.
    def visitActivityDef(self, ctx:SysMLMinParser.ActivityDefContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#typeDef.
    def visitTypeDef(self, ctx:SysMLMinParser.TypeDefContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#inheritanceClause.
    def visitInheritanceClause(self, ctx:SysMLMinParser.InheritanceClauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#partDef.
    def visitPartDef(self, ctx:SysMLMinParser.PartDefContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#itemDef.
    def visitItemDef(self, ctx:SysMLMinParser.ItemDefContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#itemUsage.
    def visitItemUsage(self, ctx:SysMLMinParser.ItemUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#requirementUsage.
    def visitRequirementUsage(self, ctx:SysMLMinParser.RequirementUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#concernUsage.
    def visitConcernUsage(self, ctx:SysMLMinParser.ConcernUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#subjectUsage.
    def visitSubjectUsage(self, ctx:SysMLMinParser.SubjectUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#objectiveUsage.
    def visitObjectiveUsage(self, ctx:SysMLMinParser.ObjectiveUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#enumDef.
    def visitEnumDef(self, ctx:SysMLMinParser.EnumDefContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#enumBodyElement.
    def visitEnumBodyElement(self, ctx:SysMLMinParser.EnumBodyElementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#enumLiteralValue.
    def visitEnumLiteralValue(self, ctx:SysMLMinParser.EnumLiteralValueContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#enumLiteralBody.
    def visitEnumLiteralBody(self, ctx:SysMLMinParser.EnumLiteralBodyContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#attributeDef.
    def visitAttributeDef(self, ctx:SysMLMinParser.AttributeDefContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#partBodyElement.
    def visitPartBodyElement(self, ctx:SysMLMinParser.PartBodyElementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#featureUsage.
    def visitFeatureUsage(self, ctx:SysMLMinParser.FeatureUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#partUsage.
    def visitPartUsage(self, ctx:SysMLMinParser.PartUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#attributeUsage.
    def visitAttributeUsage(self, ctx:SysMLMinParser.AttributeUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#valueBindingStmt.
    def visitValueBindingStmt(self, ctx:SysMLMinParser.ValueBindingStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#multiplicitySpec.
    def visitMultiplicitySpec(self, ctx:SysMLMinParser.MultiplicitySpecContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#multiplicityModifiers.
    def visitMultiplicityModifiers(self, ctx:SysMLMinParser.MultiplicityModifiersContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#multiplicityBracket.
    def visitMultiplicityBracket(self, ctx:SysMLMinParser.MultiplicityBracketContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#multiplicityBound.
    def visitMultiplicityBound(self, ctx:SysMLMinParser.MultiplicityBoundContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#connectUsage.
    def visitConnectUsage(self, ctx:SysMLMinParser.ConnectUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#connectionUsage.
    def visitConnectionUsage(self, ctx:SysMLMinParser.ConnectionUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#connectorEnd.
    def visitConnectorEnd(self, ctx:SysMLMinParser.ConnectorEndContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#connectorEndPath.
    def visitConnectorEndPath(self, ctx:SysMLMinParser.ConnectorEndPathContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#qualifiedName.
    def visitQualifiedName(self, ctx:SysMLMinParser.QualifiedNameContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#flowUsage.
    def visitFlowUsage(self, ctx:SysMLMinParser.FlowUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#flowDef.
    def visitFlowDef(self, ctx:SysMLMinParser.FlowDefContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#actionDef.
    def visitActionDef(self, ctx:SysMLMinParser.ActionDefContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#actionBodyElement.
    def visitActionBodyElement(self, ctx:SysMLMinParser.ActionBodyElementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#actionParameter.
    def visitActionParameter(self, ctx:SysMLMinParser.ActionParameterContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#direction.
    def visitDirection(self, ctx:SysMLMinParser.DirectionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#flowControlNode.
    def visitFlowControlNode(self, ctx:SysMLMinParser.FlowControlNodeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#assignmentStmt.
    def visitAssignmentStmt(self, ctx:SysMLMinParser.AssignmentStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#sendActionNamed.
    def visitSendActionNamed(self, ctx:SysMLMinParser.SendActionNamedContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#sendActionAnonymous.
    def visitSendActionAnonymous(self, ctx:SysMLMinParser.SendActionAnonymousContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#acceptActionStmt.
    def visitAcceptActionStmt(self, ctx:SysMLMinParser.AcceptActionStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#performActionStmt.
    def visitPerformActionStmt(self, ctx:SysMLMinParser.PerformActionStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#messageStmt.
    def visitMessageStmt(self, ctx:SysMLMinParser.MessageStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#messageUsage.
    def visitMessageUsage(self, ctx:SysMLMinParser.MessageUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#ifActionStmt.
    def visitIfActionStmt(self, ctx:SysMLMinParser.IfActionStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#guardedTargetSuccessionStmt.
    def visitGuardedTargetSuccessionStmt(self, ctx:SysMLMinParser.GuardedTargetSuccessionStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#defaultTargetSuccessionStmt.
    def visitDefaultTargetSuccessionStmt(self, ctx:SysMLMinParser.DefaultTargetSuccessionStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#actionUsageStmt.
    def visitActionUsageStmt(self, ctx:SysMLMinParser.ActionUsageStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#requirementDef.
    def visitRequirementDef(self, ctx:SysMLMinParser.RequirementDefContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#requirementBodyElement.
    def visitRequirementBodyElement(self, ctx:SysMLMinParser.RequirementBodyElementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#concernDef.
    def visitConcernDef(self, ctx:SysMLMinParser.ConcernDefContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#stateDef.
    def visitStateDef(self, ctx:SysMLMinParser.StateDefContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#stateBodyElement.
    def visitStateBodyElement(self, ctx:SysMLMinParser.StateBodyElementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#stateUsage.
    def visitStateUsage(self, ctx:SysMLMinParser.StateUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#initialTransitionMember.
    def visitInitialTransitionMember(self, ctx:SysMLMinParser.InitialTransitionMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#bindingConnector.
    def visitBindingConnector(self, ctx:SysMLMinParser.BindingConnectorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#successionStmt.
    def visitSuccessionStmt(self, ctx:SysMLMinParser.SuccessionStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#successionUsageFirstThen.
    def visitSuccessionUsageFirstThen(self, ctx:SysMLMinParser.SuccessionUsageFirstThenContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#successionUsageFlow.
    def visitSuccessionUsageFlow(self, ctx:SysMLMinParser.SuccessionUsageFlowContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#bareFirstStmt.
    def visitBareFirstStmt(self, ctx:SysMLMinParser.BareFirstStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#bareThenStmt.
    def visitBareThenStmt(self, ctx:SysMLMinParser.BareThenStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#actionFlowFrom.
    def visitActionFlowFrom(self, ctx:SysMLMinParser.ActionFlowFromContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#actionFlowShort.
    def visitActionFlowShort(self, ctx:SysMLMinParser.ActionFlowShortContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#entryActionMember.
    def visitEntryActionMember(self, ctx:SysMLMinParser.EntryActionMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#doActionMember.
    def visitDoActionMember(self, ctx:SysMLMinParser.DoActionMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#exitActionMember.
    def visitExitActionMember(self, ctx:SysMLMinParser.ExitActionMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#transitionTrigger.
    def visitTransitionTrigger(self, ctx:SysMLMinParser.TransitionTriggerContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#transitionEffect.
    def visitTransitionEffect(self, ctx:SysMLMinParser.TransitionEffectContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#transitionStmt.
    def visitTransitionStmt(self, ctx:SysMLMinParser.TransitionStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#newExpr.
    def visitNewExpr(self, ctx:SysMLMinParser.NewExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#namespacePathRefExpr.
    def visitNamespacePathRefExpr(self, ctx:SysMLMinParser.NamespacePathRefExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#powerExpr.
    def visitPowerExpr(self, ctx:SysMLMinParser.PowerExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#metaExpr.
    def visitMetaExpr(self, ctx:SysMLMinParser.MetaExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#sequenceExpr.
    def visitSequenceExpr(self, ctx:SysMLMinParser.SequenceExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#parenExpr.
    def visitParenExpr(self, ctx:SysMLMinParser.ParenExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#unaryMinusExpr.
    def visitUnaryMinusExpr(self, ctx:SysMLMinParser.UnaryMinusExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#arrowCallExpr.
    def visitArrowCallExpr(self, ctx:SysMLMinParser.ArrowCallExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#literalExpr.
    def visitLiteralExpr(self, ctx:SysMLMinParser.LiteralExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#functionCallExpr.
    def visitFunctionCallExpr(self, ctx:SysMLMinParser.FunctionCallExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#asCastExpr.
    def visitAsCastExpr(self, ctx:SysMLMinParser.AsCastExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#memberAccessExpr.
    def visitMemberAccessExpr(self, ctx:SysMLMinParser.MemberAccessExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#quantityLiteralExpr.
    def visitQuantityLiteralExpr(self, ctx:SysMLMinParser.QuantityLiteralExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#conditionalExpr.
    def visitConditionalExpr(self, ctx:SysMLMinParser.ConditionalExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#addSubExpr.
    def visitAddSubExpr(self, ctx:SysMLMinParser.AddSubExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#logicalAndExpr.
    def visitLogicalAndExpr(self, ctx:SysMLMinParser.LogicalAndExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#relationalExpr.
    def visitRelationalExpr(self, ctx:SysMLMinParser.RelationalExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#logicalOrExpr.
    def visitLogicalOrExpr(self, ctx:SysMLMinParser.LogicalOrExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#indexExpr.
    def visitIndexExpr(self, ctx:SysMLMinParser.IndexExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#notExpr.
    def visitNotExpr(self, ctx:SysMLMinParser.NotExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#impliesExpr.
    def visitImpliesExpr(self, ctx:SysMLMinParser.ImpliesExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#nameRefExpr.
    def visitNameRefExpr(self, ctx:SysMLMinParser.NameRefExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#arrowLambdaExpr.
    def visitArrowLambdaExpr(self, ctx:SysMLMinParser.ArrowLambdaExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#emptySequenceExpr.
    def visitEmptySequenceExpr(self, ctx:SysMLMinParser.EmptySequenceExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#mulDivExpr.
    def visitMulDivExpr(self, ctx:SysMLMinParser.MulDivExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#rangeExpr.
    def visitRangeExpr(self, ctx:SysMLMinParser.RangeExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#equalityExpr.
    def visitEqualityExpr(self, ctx:SysMLMinParser.EqualityExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#literal.
    def visitLiteral(self, ctx:SysMLMinParser.LiteralContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#arrowLambdaBody.
    def visitArrowLambdaBody(self, ctx:SysMLMinParser.ArrowLambdaBodyContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#lambdaParam.
    def visitLambdaParam(self, ctx:SysMLMinParser.LambdaParamContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#newArgument.
    def visitNewArgument(self, ctx:SysMLMinParser.NewArgumentContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#portDef.
    def visitPortDef(self, ctx:SysMLMinParser.PortDefContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#portUsage.
    def visitPortUsage(self, ctx:SysMLMinParser.PortUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#importStmt.
    def visitImportStmt(self, ctx:SysMLMinParser.ImportStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#visibilityIndicator.
    def visitVisibilityIndicator(self, ctx:SysMLMinParser.VisibilityIndicatorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#namespacePath.
    def visitNamespacePath(self, ctx:SysMLMinParser.NamespacePathContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#namespacePathList.
    def visitNamespacePathList(self, ctx:SysMLMinParser.NamespacePathListContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#exposeStmt.
    def visitExposeStmt(self, ctx:SysMLMinParser.ExposeStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#interfaceDef.
    def visitInterfaceDef(self, ctx:SysMLMinParser.InterfaceDefContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLMinParser#simpleName.
    def visitSimpleName(self, ctx:SysMLMinParser.SimpleNameContext):
        return self.visitChildren(ctx)



del SysMLMinParser